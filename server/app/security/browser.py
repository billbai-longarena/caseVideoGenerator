from __future__ import annotations

import hmac
import secrets
from collections.abc import Iterable

from fastapi import Request, Response

from server.app.core.errors import AppError


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def trusted_origins(request: Request) -> frozenset[str]:
    settings = request.app.state.settings
    configured: Iterable[str] = settings.csrf_trusted_origins or settings.cors_origins
    origins = {origin.rstrip("/") for origin in configured if origin}
    # A same-origin browser request is safe without an additional deployment
    # setting.  Keep explicit origins for reverse proxies whose public scheme
    # or host cannot be reconstructed from the forwarded request.
    host = request.headers.get("host")
    if host:
        origins.add(f"{request.url.scheme}://{host}".rstrip("/"))
    return frozenset(origins)


def enforce_browser_security(request: Request) -> None:
    """Apply origin and double-submit CSRF checks to browser mutations.

    The API uses bearer tokens. Non-browser CLI and service-account calls do
    not carry an Origin or the browser CSRF cookie and remain usable without a
    synthetic browser token. Once a request identifies itself as a browser
    context, both the allowlisted Origin and matching cookie/header are
    mandatory.
    """

    settings = request.app.state.settings
    if request.method.upper() in SAFE_METHODS:
        return
    origin = (request.headers.get("Origin") or "").rstrip("/")
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    session_cookie = request.cookies.get(settings.session_cookie_name)
    browser_context = bool(origin or cookie_token or session_cookie)
    if not browser_context:
        return
    if origin not in trusted_origins(request):
        raise AppError("forbidden", "browser origin is not allowed")
    # This endpoint is the bootstrap for the double-submit token. Its Origin
    # is still checked, but requiring an existing token here would make the
    # browser flow impossible to start.
    if request.url.path in {"/v1/session/csrf", "/auth/static"}:
        return
    if not settings.csrf_enabled:
        return
    header_token = request.headers.get(settings.csrf_header_name)
    if not cookie_token or not header_token:
        raise AppError("forbidden", "CSRF token is required")
    if not hmac.compare_digest(cookie_token, header_token):
        raise AppError("forbidden", "CSRF token validation failed")


def issue_csrf_cookie(request: Request, response: Response) -> str:
    settings = request.app.state.settings
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and origin not in trusted_origins(request):
        raise AppError("forbidden", "browser origin is not allowed")
    # Keep one double-submit token stable for the browser session. Rotating it
    # on every page load invalidates already-open tabs because they retain the
    # previous header value while sharing the newly overwritten cookie.
    existing = request.cookies.get(settings.csrf_cookie_name, "")
    valid_existing = 32 <= len(existing) <= 128 and all(
        character.isalnum() or character in "-_" for character in existing
    )
    token = existing if valid_existing else secrets.token_urlsafe(32)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=8 * 60 * 60,
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite="strict",
        path="/",
    )
    return token
