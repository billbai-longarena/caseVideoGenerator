from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from server.app.core.config import Settings
from server.app.core.errors import AppError
from server.app.security.auth import OIDCVerifier, Principal, require_principal


class SessionMembershipRepository(Protocol):
    def memberships_for_subject(self, oidc_subject: str) -> list[dict[str, Any]]: ...


TokenExchange = Callable[[Mapping[str, str]], Mapping[str, Any]]


@dataclass(frozen=True)
class BrowserSession:
    subject: str
    tenant_id: str
    scopes: frozenset[str]
    issued_at: int
    expires_at: int
    reauthenticated_at: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": "browser-session",
            "subject": self.subject,
            "tenant_id": self.tenant_id,
            "scopes": sorted(self.scopes),
            "iat": self.issued_at,
            "exp": self.expires_at,
            "reauth_at": self.reauthenticated_at,
        }


class StaticLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=1, max_length=4096)
    tenant_id: str | None = Field(None, min_length=1, max_length=255)


class TenantSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=1, max_length=255)


class WebSessionManager:
    """OIDC Authorization Code + PKCE browser-session boundary.

    Provider tokens are verified once at the callback and are never exposed to
    JavaScript.  The browser receives only an encrypted, HttpOnly session
    containing the selected tenant and a short, server-controlled claim set.
    """

    def __init__(
        self,
        settings: Settings,
        repository: SessionMembershipRepository,
        *,
        oidc_verifier: OIDCVerifier | None = None,
        token_exchange: TokenExchange | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.oidc_verifier = oidc_verifier
        self._token_exchange = token_exchange or self._exchange_token
        self._now = now
        self._fernet = Fernet(_fernet_key(self._session_secret()))

    def public_config(self) -> dict[str, Any]:
        return {
            "auth_mode": self.settings.auth_mode,
            "oidc_enabled": self.settings.auth_mode == "oidc",
            "session_cookie": self.settings.session_cookie_name,
            "csrf_header": self.settings.csrf_header_name,
            "login_url": "/auth/login",
            "logout_url": "/auth/logout",
            "reauth_url": "/auth/reauth",
        }

    def issue_session(
        self,
        *,
        subject: str,
        tenant_id: str,
        scopes: frozenset[str] = frozenset(),
        reauthenticated_at: int | None = None,
    ) -> str:
        now = int(self._now())
        memberships = self.repository.memberships_for_subject(subject)
        if not any(item["tenant_id"] == tenant_id for item in memberships):
            raise AppError("forbidden", "tenant membership is not authorized")
        session = BrowserSession(
            subject=subject,
            tenant_id=tenant_id,
            scopes=scopes,
            issued_at=now,
            expires_at=now + self.settings.session_max_age_seconds,
            reauthenticated_at=now if reauthenticated_at is None else reauthenticated_at,
        )
        return self._seal(session.as_payload())

    def decode_session(self, token: str) -> BrowserSession:
        payload = self._open(token, expected_kind="browser-session")
        now = int(self._now())
        if int(payload.get("exp") or 0) <= now:
            raise AppError("unauthorized", "browser session has expired")
        subject = str(payload.get("subject") or "")
        tenant_id = str(payload.get("tenant_id") or "")
        if not subject or not tenant_id:
            raise AppError("unauthorized", "browser session is invalid")
        scopes = payload.get("scopes") or []
        return BrowserSession(
            subject=subject,
            tenant_id=tenant_id,
            scopes=frozenset(str(item) for item in scopes if str(item)),
            issued_at=int(payload.get("iat") or 0),
            expires_at=int(payload["exp"]),
            reauthenticated_at=int(payload.get("reauth_at") or 0),
        )

    def begin_authorization(
        self,
        *,
        return_to: str,
        reauthenticate: bool,
        current_session: BrowserSession | None = None,
    ) -> RedirectResponse:
        self._validate_oidc_browser_config()
        safe_return = _safe_return_to(return_to)
        verifier = secrets.token_urlsafe(64)
        nonce = secrets.token_urlsafe(32)
        state = secrets.token_urlsafe(32)
        now = int(self._now())
        state_payload: dict[str, Any] = {
            "kind": "oidc-state",
            "state": state,
            "verifier": verifier,
            "nonce": nonce,
            "return_to": safe_return,
            "reauth": reauthenticate,
            "iat": now,
            "exp": now + self.settings.oidc_state_max_age_seconds,
        }
        if current_session is not None:
            state_payload["expected_subject"] = current_session.subject
            state_payload["tenant_id"] = current_session.tenant_id
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        query = {
            "response_type": "code",
            "client_id": str(self.settings.oidc_client_id),
            "redirect_uri": str(self.settings.oidc_redirect_uri),
            "scope": " ".join(self.settings.oidc_scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if reauthenticate:
            query["prompt"] = "login"
            query["max_age"] = "0"
        response = RedirectResponse(
            f"{self.settings.oidc_authorization_endpoint}?{urlencode(query)}",
            status_code=302,
        )
        response.set_cookie(
            self.settings.session_state_cookie_name,
            self._seal(state_payload),
            max_age=self.settings.oidc_state_max_age_seconds,
            secure=self.settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
            path="/auth/callback",
        )
        return response

    def complete_authorization(self, *, code: str, state: str, state_cookie: str | None) -> tuple[str, str]:
        if not state_cookie:
            raise AppError("unauthorized", "OIDC state cookie is missing")
        payload = self._open(state_cookie, expected_kind="oidc-state")
        now = int(self._now())
        if int(payload.get("exp") or 0) <= now:
            raise AppError("unauthorized", "OIDC authorization state has expired")
        expected_state = str(payload.get("state") or "")
        if not expected_state or not hmac.compare_digest(expected_state, state):
            raise AppError("unauthorized", "OIDC state validation failed")
        token_response = self._token_exchange(
            {
                "grant_type": "authorization_code",
                "client_id": str(self.settings.oidc_client_id),
                "code": code,
                "redirect_uri": str(self.settings.oidc_redirect_uri),
                "code_verifier": str(payload["verifier"]),
            }
        )
        token = token_response.get("id_token") or token_response.get("access_token")
        if not isinstance(token, str) or not token:
            raise AppError("unauthorized", "OIDC provider did not return a verifiable token")
        verifier = self.oidc_verifier or OIDCVerifier(self.settings)
        claims, token_kind = verifier.verify(token, supplied_nonce=str(payload["nonce"]))
        if token_kind != "user":
            raise AppError("unauthorized", "service credentials cannot create browser sessions")
        subject = str(claims["sub"])
        expected_subject = payload.get("expected_subject")
        if expected_subject and not hmac.compare_digest(str(expected_subject), subject):
            raise AppError("unauthorized", "reauthentication identity changed")
        memberships = self.repository.memberships_for_subject(subject)
        if not memberships:
            raise AppError("forbidden", "no active tenant membership")
        preferred_tenant = payload.get("tenant_id")
        selected = next(
            (item for item in memberships if item["tenant_id"] == preferred_tenant),
            memberships[0],
        )
        scopes = _scopes_from_claims(claims)
        return (
            self.issue_session(
                subject=subject,
                tenant_id=str(selected["tenant_id"]),
                scopes=scopes,
                reauthenticated_at=now,
            ),
            _safe_return_to(str(payload.get("return_to") or "/jobs")),
        )

    def switch_tenant(self, session: BrowserSession, tenant_id: str) -> str:
        return self.issue_session(
            subject=session.subject,
            tenant_id=tenant_id,
            scopes=session.scopes,
            reauthenticated_at=session.reauthenticated_at,
        )

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            self.settings.session_cookie_name,
            token,
            max_age=self.settings.session_max_age_seconds,
            secure=self.settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
            path="/",
        )

    def clear_session_cookies(self, response: Response) -> None:
        response.delete_cookie(
            self.settings.session_cookie_name,
            secure=self.settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
            path="/",
        )
        response.delete_cookie(
            self.settings.session_state_cookie_name,
            secure=self.settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
            path="/auth/callback",
        )

    def _session_secret(self) -> str:
        secret = os.getenv(self.settings.session_secret_env)
        if secret:
            return secret
        if self.settings.auth_mode == "static-token" and self.settings.api_token:
            return f"static-session:{self.settings.api_token}"
        raise RuntimeError(
            f"{self.settings.session_secret_env} is required for browser sessions"
        )

    def _validate_oidc_browser_config(self) -> None:
        required = {
            "authorization endpoint": self.settings.oidc_authorization_endpoint,
            "token endpoint": self.settings.oidc_token_endpoint,
            "client id": self.settings.oidc_client_id,
            "redirect URI": self.settings.oidc_redirect_uri,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise AppError("internal_error", f"OIDC browser configuration is incomplete: {', '.join(missing)}")

    def _exchange_token(self, payload: Mapping[str, str]) -> Mapping[str, Any]:
        self._validate_oidc_browser_config()
        secret = os.getenv(self.settings.oidc_client_secret_env)
        form = dict(payload)
        if secret:
            form["client_secret"] = secret
        try:
            response = httpx.post(
                str(self.settings.oidc_token_endpoint),
                data=form,
                headers={"Accept": "application/json"},
                timeout=20.0,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("unauthorized", "OIDC token exchange failed") from exc
        if not isinstance(body, dict):
            raise AppError("unauthorized", "OIDC token response is invalid")
        return body

    def _seal(self, payload: Mapping[str, Any]) -> str:
        import json

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw).decode("ascii")

    def _open(self, token: str, *, expected_kind: str) -> dict[str, Any]:
        import json

        try:
            raw = self._fernet.decrypt(token.encode("ascii"))
            payload = json.loads(raw)
        except (InvalidToken, UnicodeError, ValueError, TypeError) as exc:
            raise AppError("unauthorized", "browser session is invalid") from exc
        if not isinstance(payload, dict) or payload.get("kind") != expected_kind:
            raise AppError("unauthorized", "browser session is invalid")
        return payload


def build_auth_router(manager: WebSessionManager) -> APIRouter:
    router = APIRouter(prefix="/auth", include_in_schema=False)

    @router.get("/config")
    def auth_config() -> dict[str, Any]:
        return manager.public_config()

    @router.get("/login")
    def login(return_to: str = Query("/jobs", max_length=2048)) -> RedirectResponse:
        if manager.settings.auth_mode != "oidc":
            raise AppError("request_invalid", "OIDC login is not enabled")
        return manager.begin_authorization(return_to=return_to, reauthenticate=False)

    @router.get("/reauth")
    def reauthenticate(
        request: Request,
        return_to: str = Query("/jobs", max_length=2048),
        principal: Principal = Depends(require_principal),
    ) -> RedirectResponse:
        del principal
        session = _request_browser_session(request)
        return manager.begin_authorization(
            return_to=return_to,
            reauthenticate=True,
            current_session=session,
        )

    @router.get("/callback")
    def callback(
        request: Request,
        code: str = Query(..., min_length=1, max_length=8192),
        state: str = Query(..., min_length=1, max_length=4096),
    ) -> RedirectResponse:
        token, return_to = manager.complete_authorization(
            code=code,
            state=state,
            state_cookie=request.cookies.get(manager.settings.session_state_cookie_name),
        )
        response = RedirectResponse(return_to, status_code=303)
        manager.set_session_cookie(response, token)
        response.delete_cookie(
            manager.settings.session_state_cookie_name,
            secure=manager.settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
            path="/auth/callback",
        )
        return response

    @router.post("/static")
    def static_login(payload: StaticLoginRequest) -> JSONResponse:
        if manager.settings.auth_mode != "static-token":
            raise AppError("not_found", "resource not found")
        expected = manager.settings.api_token
        if not expected or not hmac.compare_digest(payload.token, expected):
            raise AppError("unauthorized", "invalid static token")
        tenant_id = payload.tenant_id or manager.settings.default_tenant_id
        token = manager.issue_session(
            subject=manager.settings.bootstrap_subject,
            tenant_id=tenant_id,
        )
        response = JSONResponse({"status": "authenticated", "tenant_id": tenant_id})
        manager.set_session_cookie(response, token)
        return response

    @router.post("/tenant")
    def switch_tenant(
        payload: TenantSwitchRequest,
        request: Request,
        _: Principal = Depends(require_principal),
    ) -> JSONResponse:
        session = _request_browser_session(request)
        token = manager.switch_tenant(session, payload.tenant_id)
        response = JSONResponse({"tenant_id": payload.tenant_id, "reload": True})
        manager.set_session_cookie(response, token)
        return response

    @router.post("/logout")
    def logout() -> Response:
        response = Response(status_code=204)
        manager.clear_session_cookies(response)
        return response

    return router


def _request_browser_session(request: Request) -> BrowserSession:
    session = getattr(request.state, "web_session", None)
    if isinstance(session, BrowserSession):
        return session
    token = request.cookies.get(request.app.state.settings.session_cookie_name)
    if not token:
        raise AppError("unauthorized", "browser session is required")
    session = request.app.state.web_sessions.decode_session(token)
    request.state.web_session = session
    return session


def _fernet_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def _safe_return_to(value: str) -> str:
    candidate = value.strip() or "/jobs"
    if not candidate.startswith("/") or candidate.startswith("//") or "\\" in candidate:
        return "/jobs"
    return candidate


def _scopes_from_claims(claims: Mapping[str, Any]) -> frozenset[str]:
    raw = claims.get("scope", claims.get("scp", ""))
    if isinstance(raw, str):
        return frozenset(item for item in raw.split() if item)
    if isinstance(raw, (list, tuple, set)):
        return frozenset(str(item) for item in raw if str(item))
    return frozenset()
