from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.requests import Request

from server.app.core.config import load_settings
from server.app.core.errors import AppError
from server.app.persistence.database import Database
from server.app.persistence.repository import PhaseCRepository
from server.app.security.auth import Authenticator, OIDCVerifier, Permission


@pytest.fixture()
def auth_context(tmp_path: Path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'auth.sqlite'}")
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_a", name="Tenant A")
    repository.ensure_tenant("ten_b", name="Tenant B")
    repository.ensure_user("usr_viewer", oidc_subject="sub_viewer", display_name="Viewer")
    repository.ensure_user("usr_editor", oidc_subject="sub_editor", display_name="Editor")
    repository.ensure_user("usr_producer", oidc_subject="sub_producer", display_name="Producer")
    repository.ensure_user("usr_admin", oidc_subject="sub_admin", display_name="Admin")
    repository.ensure_user("svc_worker", oidc_subject="sub_worker", display_name="Worker")
    repository.set_membership("ten_a", "usr_viewer", "viewer")
    repository.set_membership("ten_a", "usr_editor", "editor")
    repository.set_membership("ten_a", "usr_producer", "producer")
    repository.set_membership("ten_a", "usr_admin", "admin")
    repository.set_membership("ten_b", "usr_admin", "viewer")
    repository.set_membership("ten_a", "svc_worker", "admin")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    settings = replace(
        load_settings(),
        deployment_mode="distributed",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="case-video-api",
        oidc_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        oidc_algorithms=("RS256",),
        oidc_require_nonce=True,
        service_account_scope="case-video.worker",
    )
    verifier = OIDCVerifier(settings, signing_key_resolver=lambda _token: public_key)
    authenticator = Authenticator(settings, repository, oidc_verifier=verifier)
    try:
        yield settings, repository, private_key, verifier, authenticator
    finally:
        database.dispose()


def token_for(
    settings,
    private_key,
    subject: str,
    *,
    nonce: str | None = "nonce-123",
    expires_delta: timedelta = timedelta(minutes=5),
    issuer: str | None = None,
    audience: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "iss": issuer or settings.oidc_issuer,
        "aud": audience or settings.oidc_audience,
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if nonce is not None:
        claims["nonce"] = nonce
    claims.update(extra or {})
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


def request_for(token: str, *, tenant: str | None = None, nonce: str | None = "nonce-123") -> Request:
    headers = [(b"authorization", f"Bearer {token}".encode("utf-8"))]
    if tenant:
        headers.append((b"x-tenant-id", tenant.encode("utf-8")))
    if nonce:
        headers.append((b"x-oidc-nonce", nonce.encode("utf-8")))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_oidc_verifies_signature_issuer_audience_expiry_and_nonce(auth_context) -> None:
    settings, _, private_key, verifier, _ = auth_context
    valid = token_for(settings, private_key, "sub_editor")
    claims, kind = verifier.verify(valid, supplied_nonce="nonce-123")
    assert claims["sub"] == "sub_editor"
    assert kind == "user"

    invalid_cases = [
        (token_for(settings, private_key, "sub_editor", issuer="https://wrong.example"), "nonce-123"),
        (token_for(settings, private_key, "sub_editor", audience="wrong-api"), "nonce-123"),
        (token_for(settings, private_key, "sub_editor", expires_delta=timedelta(seconds=-1)), "nonce-123"),
        (valid, "wrong-nonce"),
        (token_for(settings, private_key, "sub_editor", nonce=None), None),
    ]
    for token, nonce in invalid_cases:
        with pytest.raises(AppError) as caught:
            verifier.verify(token, supplied_nonce=nonce)
        assert caught.value.code == "unauthorized"

    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = token_for(settings, attacker_key, "sub_editor")
    with pytest.raises(AppError) as caught:
        verifier.verify(forged, supplied_nonce="nonce-123")
    assert caught.value.code == "unauthorized"


def test_service_account_requires_worker_scope_and_does_not_use_browser_nonce(auth_context) -> None:
    settings, _, private_key, verifier, _ = auth_context
    valid = token_for(
        settings,
        private_key,
        "sub_worker",
        nonce=None,
        extra={"gty": "client-credentials", "scope": "case-video.worker metrics.write"},
    )
    _, kind = verifier.verify(valid, supplied_nonce=None)
    assert kind == "service"

    insufficient = token_for(
        settings,
        private_key,
        "sub_worker",
        nonce=None,
        extra={"gty": "client-credentials", "scope": "metrics.write"},
    )
    with pytest.raises(AppError) as caught:
        verifier.verify(insufficient, supplied_nonce=None)
    assert caught.value.code == "forbidden"


@pytest.mark.parametrize(
    ("subject", "allowed", "denied"),
    [
        ("sub_viewer", Permission.JOBS_READ, Permission.JOBS_CREATE),
        ("sub_editor", Permission.JOBS_CREATE, Permission.APPROVALS_DECIDE),
        ("sub_producer", Permission.APPROVALS_DECIDE, Permission.GOVERNANCE_WRITE),
        ("sub_admin", Permission.GOVERNANCE_WRITE, None),
    ],
)
def test_database_role_is_the_authority_for_permissions(
    auth_context,
    subject: str,
    allowed: Permission,
    denied: Permission | None,
) -> None:
    settings, _, private_key, _, authenticator = auth_context
    token = token_for(
        settings,
        private_key,
        subject,
        extra={"role": "admin", "tenant_id": "ten_b"},
    )
    tenant = "ten_a" if subject == "sub_admin" else None
    principal = authenticator.authenticate(request_for(token, tenant=tenant))
    assert principal.tenant_id == "ten_a"
    assert principal.can(allowed)
    if denied is not None:
        assert not principal.can(denied)


def test_multi_tenant_subject_requires_explicit_authorized_tenant(auth_context) -> None:
    settings, _, private_key, _, authenticator = auth_context
    token = token_for(settings, private_key, "sub_admin")
    with pytest.raises(AppError) as missing:
        authenticator.authenticate(request_for(token))
    assert missing.value.status_code == 400

    tenant_b = authenticator.authenticate(request_for(token, tenant="ten_b"))
    assert tenant_b.tenant_id == "ten_b"
    assert tenant_b.role == "viewer"

    with pytest.raises(AppError) as guessed:
        authenticator.authenticate(request_for(token, tenant="ten_unknown"))
    assert guessed.value.code == "forbidden"
