from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.app.api.capabilities import router as capabilities_router
from server.app.api.distributed_reviews import router as distributed_reviews_router
from server.app.api.health import router as health_router
from server.app.api.jobs import router as jobs_router
from server.app.api.phase_c import router as phase_c_router
from server.app.api.reviews import router as reviews_router
from server.app.api.uploads import router as uploads_router
from server.app.core.config import Settings, load_settings
from server.app.core.errors import AppError, request_id_from_scope
from server.app.persistence.database import Database
from server.app.persistence.object_store import (
    ObjectNotFound,
    ObjectStore,
    ObjectStoreError,
    SignedObjectTokenService,
    object_store_from_settings,
)
from server.app.persistence.repository import (
    BudgetApprovalRequired,
    PhaseCRepository,
    QuotaExceeded,
    RepositoryConflict,
    RepositoryError,
    RepositoryNotFound,
)
from server.app.observability import (
    MetricsRegistry,
    PhaseCMetricsCollector,
    RequestObservation,
    log_request,
    monotonic_seconds,
    route_template,
    trace_id_for_request,
)
from server.app.security.auth import Authenticator, Permission, require_permission
from server.app.security.browser import enforce_browser_security
from server.app.security.rate_limit import build_rate_limiter, enforce_rate_limit
from server.app.security.uploads import UploadScanner, upload_scanner_from_settings
from server.app.security.web_session import WebSessionManager, build_auth_router
from server.app.services.model_gateway import ModelGateway
from server.app.services.distributed_revisions import DistributedRevisionService
from server.app.services.queue import JobQueue, build_queue
from server.app.services.revisions import RevisionService
from server.app.services.source_ingestion import SourceIngestion
from server.app.services.storage import JobStorage
from server.app.services.uploads import UploadStorage
from server.app.ui import router as ui_router


def require_auth(request: Request, authorization: str | None = Header(None)) -> None:
    token = request.app.state.settings.api_token
    if not token:
        return
    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def _object_signer_from_settings(settings: Settings) -> SignedObjectTokenService:
    secret = os.getenv(settings.object_store_signing_secret_env)
    if not secret:
        raise RuntimeError(
            f"{settings.object_store_signing_secret_env} is required in distributed deployment mode"
        )
    return SignedObjectTokenService(secret.encode("utf-8"))


def create_app(
    settings: Settings | None = None,
    storage: JobStorage | None = None,
    queue: JobQueue | None = None,
    *,
    database: Database | None = None,
    repository: PhaseCRepository | None = None,
    object_store: ObjectStore | None = None,
    object_signer: SignedObjectTokenService | None = None,
    upload_scanner: UploadScanner | None = None,
    authenticator: Authenticator | None = None,
    web_session_manager: WebSessionManager | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    distributed = app_settings.deployment_mode == "distributed"

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if distributed:
            # Schema changes are an explicit deploy job. API startup must never
            # mutate production data structures implicitly.
            application.state.database.check_schema()
        yield

    app = FastAPI(
        title="Case Video Generator Server",
        version="0.3.0",
        dependencies=[] if distributed else [Depends(require_auth)],
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.metrics = MetricsRegistry()
    app.state.model_gateway = ModelGateway(app_settings)
    app.state.model_gateway.validate_required_routes(
        require_provider_config=(
            app_settings.require_model_config
            or (distributed and not app_settings.dry_run)
        )
    )
    if distributed:
        app.state.database = database or Database.from_settings(app_settings)
        app.state.repository = repository or PhaseCRepository(app.state.database)
        app.state.object_store = object_store or object_store_from_settings(app_settings)
        app.state.upload_scanner = upload_scanner or upload_scanner_from_settings(app_settings)
        app.state.object_signer = object_signer or _object_signer_from_settings(app_settings)
        app.state.authenticator = authenticator or Authenticator(app_settings, app.state.repository)
        app.state.web_sessions = web_session_manager or WebSessionManager(
            app_settings,
            app.state.repository,
            oidc_verifier=app.state.authenticator.oidc_verifier,
        )
        app.state.rate_limiter = build_rate_limiter(app_settings)
        app.state.phase_c_metrics = PhaseCMetricsCollector(
            app_settings,
            app.state.repository,
            app.state.object_store,
        )
        app.state.distributed_revisions = DistributedRevisionService(
            app_settings,
            app.state.repository,
            app.state.object_store,
        )

    else:
        app.state.storage = storage or JobStorage(app_settings)
        app.state.uploads = UploadStorage(app_settings)
        app.state.queue = queue or build_queue(app_settings)
        app.state.model_gateway = ModelGateway(app_settings, app.state.storage)
        app.state.revisions = RevisionService(app.state.storage, app.state.model_gateway)
        app.state.ingestion = SourceIngestion(app_settings, app.state.storage, app.state.uploads)

    if distributed and app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(app_settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "If-Match",
                "Last-Event-ID",
                "X-Request-ID",
                app_settings.csrf_header_name,
                app_settings.oidc_nonce_header,
                app_settings.tenant_header,
            ],
            expose_headers=["ETag", "X-Request-ID"],
            max_age=600,
        )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: Any) -> Any:
        started = monotonic_seconds()
        supplied = request.headers.get("X-Request-ID", "").strip()
        request.state.request_id = supplied[:128] if supplied else f"req_{uuid.uuid4().hex[:16]}"
        request.state.trace_id = trace_id_for_request(request)
        status_code = 500
        try:
            if distributed:
                enforce_browser_security(request)
                enforce_rate_limit(request, app.state.rate_limiter)
            response = await call_next(request)
            status_code = response.status_code
        except AppError as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content=exc.public_payload(request_id_from_scope(request)),
            )
            status_code = exc.status_code
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Trace-ID"] = request.state.trace_id
        decision = getattr(request.state, "rate_limit", None)
        if decision is not None:
            response.headers["RateLimit-Limit"] = str(decision.limit)
            response.headers["RateLimit-Remaining"] = str(decision.remaining)
        retry_after = getattr(request.state, "rate_limit_retry_after", None)
        if retry_after is not None:
            response.headers["Retry-After"] = str(retry_after)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        duration = monotonic_seconds() - started
        app.state.metrics.observe_request(
            RequestObservation(
                method=request.method,
                route=route_template(request),
                status_code=status_code,
                duration_seconds=duration,
            )
        )
        log_request(
            request,
            status_code=status_code,
            duration_seconds=duration,
            structured=app_settings.structured_logs,
        )
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.public_payload(request_id_from_scope(request)),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = _http_error_code(exc.status_code)
        descriptor = AppError(code, _detail_message(exc.detail), status_code=exc.status_code)
        payload = descriptor.public_payload(request_id_from_scope(request))
        payload["detail"] = exc.detail
        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        descriptor = AppError("request_invalid", "request validation failed", status_code=422)
        payload = descriptor.public_payload(request_id_from_scope(request))
        payload["detail"] = _validation_errors(exc)
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(RepositoryError)
    async def handle_repository_error(request: Request, exc: RepositoryError) -> JSONResponse:
        if isinstance(exc, RepositoryNotFound):
            descriptor = AppError("not_found", "resource not found")
        elif isinstance(exc, QuotaExceeded):
            descriptor = AppError("quota_exceeded", str(exc))
        elif isinstance(exc, BudgetApprovalRequired):
            descriptor = AppError("budget_exceeded", str(exc))
        elif isinstance(exc, RepositoryConflict):
            descriptor = AppError(exc.code, str(exc))
        else:
            descriptor = AppError("internal_error", "persistence operation failed")
        return JSONResponse(
            status_code=descriptor.status_code,
            content=descriptor.public_payload(request_id_from_scope(request)),
        )

    @app.exception_handler(ObjectStoreError)
    async def handle_object_store_error(request: Request, exc: ObjectStoreError) -> JSONResponse:
        descriptor = (
            AppError("not_found", "resource not found")
            if isinstance(exc, ObjectNotFound)
            else AppError("internal_error", "object storage operation failed", status_code=503)
        )
        return JSONResponse(
            status_code=descriptor.status_code,
            content=descriptor.public_payload(request_id_from_scope(request)),
        )

    if distributed:
        if app_settings.metrics_enabled:

            @app.get(app_settings.metrics_path, include_in_schema=False)
            def metrics(
                _: Any = Depends(require_permission(Permission.WORKER_EXECUTE)),
            ) -> PlainTextResponse:
                app.state.phase_c_metrics.collect(app.state.metrics)
                return PlainTextResponse(
                    app.state.metrics.render(),
                    media_type="text/plain; version=0.0.4; charset=utf-8",
                )

        app.include_router(build_auth_router(app.state.web_sessions))
        app.include_router(distributed_reviews_router)
        app.include_router(phase_c_router)
        app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
        app.include_router(ui_router)
    else:
        app.include_router(health_router)
        app.include_router(capabilities_router)
        app.include_router(uploads_router)
        app.include_router(jobs_router)
        app.include_router(reviews_router)
        app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")
        app.include_router(ui_router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/jobs")

    return app


app = create_app()


def _detail_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    return "request failed"


def _validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Return a stable, JSON-safe field-error contract for API and UI clients."""

    normalized: list[dict[str, Any]] = []
    for raw in exc.errors():
        item = dict(raw)
        context = item.get("ctx")
        if isinstance(context, dict):
            item["ctx"] = {
                str(key): value if value is None or isinstance(value, (str, int, float, bool)) else str(value)
                for key, value in context.items()
            }
        if isinstance(item.get("input"), bytes):
            item["input"] = f"<{len(item['input'])} bytes>"
        normalized.append(item)
    return normalized


def _http_error_code(status_code: int) -> str:
    if status_code == 401:
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "revision_conflict"
    if status_code in {400, 413}:
        return "source_invalid"
    if status_code == 422:
        return "request_invalid"
    return "internal_error"
