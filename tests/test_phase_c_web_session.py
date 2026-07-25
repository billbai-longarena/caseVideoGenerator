from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from server.app.core.config import load_settings
from server.app.main import create_app
from server.app.persistence.database import Database
from server.app.persistence.object_store import LocalObjectStore, SignedObjectTokenService
from server.app.persistence.repository import PhaseCRepository
from server.app.security.auth import Authenticator
from server.app.security.uploads import upload_scanner_from_settings
from server.app.security.web_session import WebSessionManager


class FakeOIDCVerifier:
    def __init__(self, subject: str = "sub_admin") -> None:
        self.subject = subject
        self.calls: list[dict[str, Any]] = []

    def verify(self, token: str, *, supplied_nonce: str | None):
        self.calls.append({"token": token, "nonce": supplied_nonce})
        assert supplied_nonce
        return {"sub": self.subject, "scope": "openid profile email"}, "user"


@pytest.fixture()
def browser_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CASE_VIDEO_SESSION_SECRET", "test-session-secret-with-enough-entropy")
    settings = replace(
        load_settings(),
        deployment_mode="distributed",
        auth_mode="oidc",
        api_token=None,
        dry_run=True,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'browser.sqlite'}",
        object_store_backend="local",
        object_store_root=tmp_path / "objects",
        upload_scanner_mode="structural",
        oidc_issuer="https://identity.example",
        oidc_audience="case-video-api",
        oidc_jwks_url="https://identity.example/.well-known/jwks.json",
        oidc_authorization_endpoint="https://identity.example/oauth2/authorize",
        oidc_token_endpoint="https://identity.example/oauth2/token",
        oidc_client_id="case-video-browser",
        oidc_redirect_uri="https://ui.example/auth/callback",
        session_cookie_secure=True,
        csrf_trusted_origins=("https://ui.example",),
        cors_origins=("https://ui.example",),
        reauth_max_age_seconds=300,
    )
    database = Database(settings.database_url)
    database.migrate()
    repository = PhaseCRepository(database)
    repository.ensure_tenant("ten_a", name="Tenant A")
    repository.ensure_tenant("ten_b", name="Tenant B")
    repository.ensure_user(
        "usr_admin",
        oidc_subject="sub_admin",
        display_name="Admin User",
        email="admin@example.test",
    )
    repository.set_membership("ten_a", "usr_admin", "admin")
    repository.set_membership("ten_b", "usr_admin", "viewer")

    exchange_calls: list[dict[str, str]] = []

    def exchange(payload):
        exchange_calls.append(dict(payload))
        return {"id_token": "provider-id-token"}

    verifier = FakeOIDCVerifier()
    authenticator = Authenticator(settings, repository, oidc_verifier=verifier)  # type: ignore[arg-type]
    sessions = WebSessionManager(
        settings,
        repository,
        oidc_verifier=verifier,  # type: ignore[arg-type]
        token_exchange=exchange,
    )
    app = create_app(
        settings,
        database=database,
        repository=repository,
        object_store=LocalObjectStore(settings.object_store_root),
        object_signer=SignedObjectTokenService(b"browser-test-signing-secret"),
        upload_scanner=upload_scanner_from_settings(settings),
        authenticator=authenticator,
        web_session_manager=sessions,
    )
    try:
        with TestClient(app, base_url="https://ui.example") as client:
            yield {
                "client": client,
                "settings": settings,
                "repository": repository,
                "sessions": sessions,
                "verifier": verifier,
                "exchange_calls": exchange_calls,
            }
    finally:
        database.dispose()


def _login(client: TestClient, *, return_to: str = "/admin/members") -> dict[str, str]:
    started = client.get(
        "/auth/login",
        params={"return_to": return_to},
        follow_redirects=False,
    )
    assert started.status_code == 302, started.text
    query = parse_qs(urlsplit(started.headers["location"]).query)
    completed = client.get(
        "/auth/callback",
        params={"code": "authorization-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert completed.status_code == 303, completed.text
    assert completed.headers["location"] == return_to
    return {key: values[0] for key, values in query.items()}


def _csrf(client: TestClient) -> str:
    response = client.post(
        "/v1/session/csrf",
        headers={"Origin": "https://ui.example"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def test_oidc_login_uses_pkce_nonce_and_server_side_http_only_session(browser_app) -> None:
    client = browser_app["client"]
    query = _login(client)

    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"]
    assert query["nonce"]
    assert "code_verifier" not in query
    assert browser_app["exchange_calls"][0]["code_verifier"]
    assert browser_app["verifier"].calls == [
        {"token": "provider-id-token", "nonce": query["nonce"]}
    ]

    response = client.get("/v1/session")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["tenant_id"] == "ten_a"
    assert payload["role"] == "admin"
    assert {item["tenant_id"] for item in payload["memberships"]} == {"ten_a", "ten_b"}
    session_cookie = client.cookies.get(browser_app["settings"].session_cookie_name)
    assert session_cookie
    assert "provider-id-token" not in session_cookie


def test_browser_csrf_tenant_switch_and_membership_recheck(browser_app) -> None:
    client = browser_app["client"]
    _login(client, return_to="/jobs")
    csrf = _csrf(client)

    missing = client.post(
        "/auth/tenant",
        headers={"Origin": "https://ui.example"},
        json={"tenant_id": "ten_b"},
    )
    assert missing.status_code == 403

    switched = client.post(
        "/auth/tenant",
        headers={
            "Origin": "https://ui.example",
            browser_app["settings"].csrf_header_name: csrf,
        },
        json={"tenant_id": "ten_b"},
    )
    assert switched.status_code == 200, switched.text
    session = client.get("/v1/session").json()
    assert session["tenant_id"] == "ten_b"
    assert session["role"] == "viewer"

    denied = client.post(
        "/auth/tenant",
        headers={
            "Origin": "https://ui.example",
            browser_app["settings"].csrf_header_name: csrf,
        },
        json={"tenant_id": "ten_unknown"},
    )
    assert denied.status_code == 403

    browser_app["repository"].set_membership("ten_b", "usr_admin", "viewer", disabled=True)
    revoked = client.get("/v1/session")
    assert revoked.status_code == 403


def test_high_risk_browser_mutation_requires_recent_reauthentication(browser_app) -> None:
    client = browser_app["client"]
    settings = browser_app["settings"]
    stale = browser_app["sessions"].issue_session(
        subject="sub_admin",
        tenant_id="ten_a",
        reauthenticated_at=int(time.time()) - settings.reauth_max_age_seconds - 5,
    )
    client.cookies.set(settings.session_cookie_name, stale, path="/")
    csrf = _csrf(client)

    blocked = client.patch(
        "/v1/governance",
        headers={"Origin": "https://ui.example", settings.csrf_header_name: csrf},
        json={"policy": {"default_approval_mode": "full"}},
    )
    assert blocked.status_code == 401, blocked.text
    assert blocked.json()["reauthentication_required"] is True
    assert blocked.json()["action_url"].startswith("/auth/reauth?")

    reauth = client.get(blocked.json()["action_url"], follow_redirects=False)
    assert reauth.status_code == 302, reauth.text
    query = parse_qs(urlsplit(reauth.headers["location"]).query)
    assert query["prompt"] == ["login"]
    assert query["max_age"] == ["0"]


def test_tampered_session_and_unsafe_return_target_are_rejected_or_normalized(browser_app) -> None:
    client = browser_app["client"]
    settings = browser_app["settings"]
    client.cookies.set(settings.session_cookie_name, "tampered", path="/")
    assert client.get("/v1/session").status_code == 401

    client.cookies.delete(settings.session_cookie_name, path="/")
    started = client.get(
        "/auth/login",
        params={"return_to": "https://attacker.example/phish"},
        follow_redirects=False,
    )
    query = parse_qs(urlsplit(started.headers["location"]).query)
    completed = client.get(
        "/auth/callback",
        params={"code": "authorization-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    assert completed.headers["location"] == "/jobs"


def test_session_cookies_use_expected_security_attributes(browser_app) -> None:
    client = browser_app["client"]
    started = client.get("/auth/login", follow_redirects=False)
    assert "httponly" in started.headers["set-cookie"].lower()
    assert "samesite=lax" in started.headers["set-cookie"].lower()
    assert "secure" in started.headers["set-cookie"].lower()
    query = parse_qs(urlsplit(started.headers["location"]).query)
    completed = client.get(
        "/auth/callback",
        params={"code": "authorization-code", "state": query["state"][0]},
        follow_redirects=False,
    )
    cookie_header = completed.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "secure" in cookie_header
