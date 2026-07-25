from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote

import jwt
from fastapi import Depends, Request

from server.app.core.config import Settings
from server.app.core.errors import AppError


class MembershipRepository(Protocol):
    def memberships_for_subject(self, oidc_subject: str) -> list[dict[str, Any]]: ...


class Permission(str, Enum):
    JOBS_READ = "jobs.read"
    JOBS_CREATE = "jobs.create"
    JOBS_EDIT = "jobs.edit"
    JOBS_CANCEL = "jobs.cancel"
    JOBS_RETRY = "jobs.retry"
    UPLOADS_WRITE = "uploads.write"
    APPROVALS_DECIDE = "approvals.decide"
    PAID_RERUN_FORCE = "paid-rerun.force"
    COST_READ = "cost.read"
    QUOTA_READ = "quota.read"
    GOVERNANCE_READ = "governance.read"
    GOVERNANCE_WRITE = "governance.write"
    MEMBERS_MANAGE = "members.manage"
    RETENTION_MANAGE = "retention.manage"
    AUDIT_READ = "audit.read"
    WORKER_EXECUTE = "worker.execute"


VIEWER_PERMISSIONS = frozenset({Permission.JOBS_READ})
EDITOR_PERMISSIONS = VIEWER_PERMISSIONS | frozenset(
    {
        Permission.JOBS_CREATE,
        Permission.JOBS_EDIT,
        Permission.JOBS_CANCEL,
        Permission.JOBS_RETRY,
        Permission.UPLOADS_WRITE,
    }
)
PRODUCER_PERMISSIONS = EDITOR_PERMISSIONS | frozenset(
    {
        Permission.APPROVALS_DECIDE,
        Permission.PAID_RERUN_FORCE,
        Permission.COST_READ,
        Permission.QUOTA_READ,
    }
)
ADMIN_PERMISSIONS = PRODUCER_PERMISSIONS | frozenset(
    {
        Permission.GOVERNANCE_READ,
        Permission.GOVERNANCE_WRITE,
        Permission.MEMBERS_MANAGE,
        Permission.RETENTION_MANAGE,
        Permission.AUDIT_READ,
        Permission.WORKER_EXECUTE,
    }
)
ROLE_PERMISSIONS: Mapping[str, frozenset[Permission]] = {
    "viewer": VIEWER_PERMISSIONS,
    "editor": EDITOR_PERMISSIONS,
    "producer": PRODUCER_PERMISSIONS,
    "admin": ADMIN_PERMISSIONS,
}


@dataclass(frozen=True)
class Principal:
    subject: str
    actor_id: str
    tenant_id: str
    role: str
    token_kind: str
    scopes: frozenset[str]
    permissions: frozenset[Permission]
    display_name: str | None = None
    email: str | None = None

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


SigningKeyResolver = Callable[[str], Any]


class OIDCVerifier:
    """Strict OIDC access-token verifier with an injectable key resolver.

    Production uses the configured JWKS endpoint. Tests can inject a resolver
    that returns a local public key without weakening claim validation.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        signing_key_resolver: SigningKeyResolver | None = None,
    ) -> None:
        self.settings = settings
        self._resolver = signing_key_resolver or self._build_jwks_resolver()

    def verify(self, token: str, *, supplied_nonce: str | None) -> tuple[dict[str, Any], str]:
        if not self.settings.oidc_issuer or not self.settings.oidc_audience:
            raise AppError("internal_error", "OIDC issuer and audience are not configured")
        try:
            unverified_header = jwt.get_unverified_header(token)
            algorithm = str(unverified_header.get("alg") or "")
            if algorithm not in self.settings.oidc_algorithms:
                raise AppError("unauthorized", "token signing algorithm is not allowed")
            key = self._resolver(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.settings.oidc_algorithms),
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except AppError:
            raise
        except jwt.ExpiredSignatureError as exc:
            raise AppError("unauthorized", "token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AppError("unauthorized", "token validation failed") from exc
        except Exception as exc:
            raise AppError("unauthorized", "token signing key could not be resolved") from exc

        token_kind = _token_kind(claims)
        scopes = _scopes(claims)
        if token_kind == "service":
            required_scope = self.settings.service_account_scope
            if required_scope and required_scope not in scopes:
                raise AppError("forbidden", "service account scope is insufficient")
        elif self.settings.oidc_require_nonce:
            claim_nonce = claims.get("nonce")
            if not isinstance(claim_nonce, str) or not supplied_nonce:
                raise AppError("unauthorized", "OIDC nonce is required")
            if not hmac.compare_digest(claim_nonce, supplied_nonce):
                raise AppError("unauthorized", "OIDC nonce validation failed")
        return dict(claims), token_kind

    def _build_jwks_resolver(self) -> SigningKeyResolver:
        if not self.settings.oidc_jwks_url:
            raise AppError("internal_error", "OIDC JWKS URL is not configured")
        client = jwt.PyJWKClient(self.settings.oidc_jwks_url)
        return lambda token: client.get_signing_key_from_jwt(token).key


class Authenticator:
    def __init__(
        self,
        settings: Settings,
        repository: MembershipRepository,
        *,
        oidc_verifier: OIDCVerifier | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.oidc_verifier = oidc_verifier

    def authenticate(self, request: Request) -> Principal:
        scheme, token = _bearer_token(request.headers.get("Authorization"))
        if scheme == "bearer" and token:
            if self.settings.auth_mode == "static-token":
                return self._authenticate_static(token)
            if self.settings.auth_mode != "oidc":
                raise AppError("internal_error", "unsupported authentication mode")
            verifier = self.oidc_verifier or OIDCVerifier(self.settings)
            claims, token_kind = verifier.verify(
                token,
                supplied_nonce=request.headers.get(self.settings.oidc_nonce_header),
            )
            return self._principal_for_subject(
                subject=str(claims["sub"]),
                token_kind=token_kind,
                scopes=_scopes(claims),
                requested_tenant=request.headers.get(self.settings.tenant_header),
            )

        session_token = request.cookies.get(self.settings.session_cookie_name)
        session_manager = getattr(request.app.state, "web_sessions", None)
        if not session_token or session_manager is None:
            raise AppError("unauthorized", "authentication is required")
        session = session_manager.decode_session(session_token)
        request.state.web_session = session
        return self._principal_for_subject(
            subject=session.subject,
            token_kind="web",
            scopes=session.scopes,
            requested_tenant=session.tenant_id,
        )

    def _authenticate_static(self, token: str) -> Principal:
        expected = self.settings.api_token
        if not expected or not hmac.compare_digest(token, expected):
            raise AppError("unauthorized", "invalid bearer token")
        role = self.settings.default_role
        permissions = ROLE_PERMISSIONS.get(role)
        if permissions is None:
            raise AppError("internal_error", "configured default role is invalid")
        return Principal(
            subject=self.settings.default_user_id,
            actor_id=self.settings.default_user_id,
            tenant_id=self.settings.default_tenant_id,
            role=role,
            token_kind="static",
            scopes=frozenset(),
            permissions=permissions,
        )

    def _principal_for_subject(
        self,
        *,
        subject: str,
        token_kind: str,
        scopes: frozenset[str],
        requested_tenant: str | None,
    ) -> Principal:
        memberships = self.repository.memberships_for_subject(subject)
        if not memberships:
            raise AppError("forbidden", "no active tenant membership")
        selected: dict[str, Any] | None = None
        if requested_tenant:
            selected = next(
                (item for item in memberships if item["tenant_id"] == requested_tenant),
                None,
            )
            if selected is None:
                raise AppError("forbidden", "tenant membership is not authorized")
        elif len(memberships) == 1:
            selected = memberships[0]
        else:
            raise AppError(
                "request_invalid",
                "tenant selection is required",
                status_code=400,
                public_details={"tenant_header": self.settings.tenant_header},
            )
        role = str(selected["role"])
        permissions = ROLE_PERMISSIONS.get(role)
        if permissions is None:
            raise AppError("forbidden", "tenant role is not supported")
        return Principal(
            subject=subject,
            actor_id=str(selected["user_id"]),
            tenant_id=str(selected["tenant_id"]),
            role=role,
            token_kind=token_kind,
            scopes=scopes,
            permissions=permissions,
            display_name=selected.get("display_name"),
            email=selected.get("email"),
        )


def require_principal(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    principal = request.app.state.authenticator.authenticate(request)
    request.state.principal = principal
    return principal


def require_permission(
    permission: Permission,
    *,
    required_scope: str | None = None,
) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if not principal.can(permission):
            raise AppError("forbidden", "permission denied")
        if principal.token_kind == "service" and required_scope and required_scope not in principal.scopes:
            raise AppError("forbidden", "service account scope is insufficient")
        return principal

    return dependency


def require_recent_reauthentication(request: Request, principal: Principal) -> None:
    """Require a fresh browser identity proof for high-risk mutations.

    Bearer and service-account callers have already presented a fresh secret on
    this request. Browser sessions are longer lived, so only they need the
    explicit OIDC prompt before changing tenant-wide security or retention
    controls.
    """

    if principal.token_kind != "web":
        return
    session = getattr(request.state, "web_session", None)
    reauthenticated_at = int(getattr(session, "reauthenticated_at", 0) or 0)
    if reauthenticated_at and int(time.time()) - reauthenticated_at <= request.app.state.settings.reauth_max_age_seconds:
        return
    return_to = request.url.path
    if request.url.query:
        return_to = f"{return_to}?{request.url.query}"
    raise AppError(
        "unauthorized",
        "近期二次认证已过期，请重新验证身份后继续",
        action_url=f"/auth/reauth?return_to={quote(return_to, safe='')}",
        public_details={"reauthentication_required": True},
    )


def _bearer_token(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parts = value.strip().split(None, 1)
    if len(parts) != 2:
        return None, None
    return parts[0].lower(), parts[1].strip()


def _scopes(claims: Mapping[str, Any]) -> frozenset[str]:
    raw = claims.get("scope", claims.get("scp", ""))
    if isinstance(raw, str):
        return frozenset(item for item in raw.split() if item)
    if isinstance(raw, (list, tuple, set)):
        return frozenset(str(item) for item in raw if str(item))
    return frozenset()


def _token_kind(claims: Mapping[str, Any]) -> str:
    markers = {
        str(claims.get("gty") or "").lower(),
        str(claims.get("grant_type") or "").lower(),
        str(claims.get("token_use") or "").lower(),
        str(claims.get("idtyp") or "").lower(),
    }
    service_markers = {"client-credentials", "client_credentials", "service", "app"}
    return "service" if markers & service_markers else "user"
