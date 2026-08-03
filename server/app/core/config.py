from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

from server.app.services.contracts import sha256_bytes


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def _csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _azure_openai_responses_base_url(value: str | None) -> str | None:
    """Accept either the Azure Responses base URL or a legacy deployment URL."""
    if not value:
        return value
    parsed = urlparse(value.strip())
    path = parsed.path.rstrip("/")
    lowered = path.lower()
    if "/openai/deployments/" in lowered:
        return urlunparse((parsed.scheme, parsed.netloc, "/openai/v1", "", "", ""))
    if lowered.endswith("/responses"):
        path = path[: -len("/responses")]
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return value.strip()


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    task_family: str
    base_url: str | None = None
    endpoint: str | None = None
    api_key_env: str | None = None
    api_version: str | None = None
    request_model: str | None = None
    auth_mode: str | None = None

    def public_dict(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "model": self.model,
            "task_family": self.task_family,
            "api_version": self.api_version,
            "transport": "anthropic_messages" if self.provider == "azure_anthropic" else "openai_responses",
        }

    def cache_fingerprint(self) -> dict[str, str | None]:
        location = self.endpoint or self.base_url or ""
        return {
            **self.public_dict(),
            "request_model": self.request_model,
            "auth_mode": self.auth_mode,
            "location_sha256": sha256_bytes(location.encode("utf-8")) if location else None,
        }


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    data_root: Path
    seed_projects_root: Path
    redis_url: str
    api_token: str | None
    dry_run: bool
    require_model_config: bool
    max_upload_bytes: int
    max_upload_files: int
    max_archive_files: int
    max_archive_expansion_bytes: int
    max_archive_compression_ratio: int
    upload_ttl_seconds: int
    max_source_text_chars: int
    max_external_excerpt_chars: int
    command_timeout_seconds: int
    narration_route: ModelRoute
    remotion_route: ModelRoute
    general_route: ModelRoute
    deployment_mode: str
    database_url: str
    database_pool_size: int
    object_store_backend: str
    object_store_root: Path
    object_store_bucket: str
    object_store_endpoint: str | None
    object_store_region: str
    object_store_access_key_env: str
    object_store_secret_key_env: str
    object_store_signing_secret_env: str
    default_tenant_id: str
    default_tenant_name: str
    default_user_id: str
    default_role: str
    bootstrap_subject: str
    bootstrap_email: str | None
    bootstrap_display_name: str | None
    auth_mode: str
    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_jwks_url: str | None
    oidc_algorithms: tuple[str, ...]
    oidc_require_nonce: bool
    oidc_nonce_header: str
    oidc_authorization_endpoint: str | None
    oidc_token_endpoint: str | None
    oidc_client_id: str | None
    oidc_client_secret_env: str
    oidc_scopes: tuple[str, ...]
    oidc_redirect_uri: str | None
    session_cookie_name: str
    session_state_cookie_name: str
    session_secret_env: str
    session_cookie_secure: bool
    session_max_age_seconds: int
    oidc_state_max_age_seconds: int
    reauth_max_age_seconds: int
    service_account_scope: str
    tenant_header: str
    cors_origins: tuple[str, ...]
    csrf_trusted_origins: tuple[str, ...]
    csrf_enabled: bool
    csrf_cookie_name: str
    csrf_header_name: str
    upload_scanner_mode: str
    clamd_host: str
    clamd_port: int
    clamd_timeout_seconds: int
    redis_namespace: str
    worker_consumer_group: str
    worker_heartbeat_seconds: int
    worker_lease_seconds: int
    worker_max_attempts: int
    worker_workspace_root: Path
    signed_url_ttl_seconds: int
    orphan_ttl_seconds: int
    deletion_recovery_days: int
    succeeded_retention_days: int
    failed_retention_days: int
    audit_retention_days: int
    maintenance_interval_seconds: int
    api_rate_limit_per_minute: int
    api_rate_limit_burst: int
    rate_limit_backend: str
    metrics_enabled: bool
    metrics_path: str
    structured_logs: bool
    render_max_seconds: int
    render_term_grace_seconds: int
    render_workspace_root: Path
    render_engine_root: Path
    render_engine_digest: str

    @property
    def model_routes(self) -> Mapping[str, ModelRoute]:
        return {
            "narration": self.narration_route,
            "remotion": self.remotion_route,
            "general": self.general_route,
        }

    def public_model_routes(self) -> dict[str, dict[str, str | None]]:
        return {
            name: route.public_dict()
            for name, route in self.model_routes.items()
        }


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def load_settings() -> Settings:
    initial_repo_root = Path(os.getenv("CASE_VIDEO_REPO_ROOT", repo_root_from_here())).resolve()
    load_dotenv(initial_repo_root / ".env", override=False)
    repo_root = Path(os.getenv("CASE_VIDEO_REPO_ROOT", initial_repo_root)).resolve()
    if repo_root != initial_repo_root:
        load_dotenv(repo_root / ".env", override=False)
    data_root = Path(os.getenv("CASE_VIDEO_DATA_ROOT", repo_root / ".casevideo-data" / "jobs")).resolve()
    seed_root = Path(os.getenv("CASE_VIDEO_SEED_PROJECTS_ROOT", repo_root / "output")).resolve()

    anthropic_endpoint = os.getenv("CASE_VIDEO_AZURE_ANTHROPIC_ENDPOINT") or os.getenv("AZURE_ANTHROPIC_ENDPOINT")
    anthropic_api_key_env = (
        "CASE_VIDEO_AZURE_ANTHROPIC_API_KEY"
        if os.getenv("CASE_VIDEO_AZURE_ANTHROPIC_API_KEY")
        else "AZURE_ANTHROPIC_API_KEY"
    )
    anthropic_deployment = (
        os.getenv("CASE_VIDEO_AZURE_ANTHROPIC_DEPLOYMENT", "case-video-claude").strip()
        or "case-video-claude"
    )
    anthropic_version = (
        os.getenv("CASE_VIDEO_AZURE_ANTHROPIC_VERSION")
        or os.getenv("AZURE_ANTHROPIC_VERSION")
        or "2023-06-01"
    )
    configured_general_base_url = os.getenv("CASE_VIDEO_GENERAL_BASE_URL")
    azure_openai_endpoint = _azure_openai_responses_base_url(os.getenv("AZURE_OPENAI_ENDPOINT"))
    general_base_url = (
        configured_general_base_url
        or azure_openai_endpoint
        or "https://api.openai.com/v1"
    )
    parsed_general_base_url = general_base_url.lower()
    general_auth_mode = os.getenv("CASE_VIDEO_GENERAL_AUTH_MODE") or (
        "api-key"
        if (
            (azure_openai_endpoint and general_base_url.rstrip("/") == azure_openai_endpoint.rstrip("/"))
            or ".azure.com/" in parsed_general_base_url
            or ".cognitiveservices.azure.com/" in parsed_general_base_url
        )
        else "bearer"
    )
    general_auth_mode = general_auth_mode.strip().lower()
    if os.getenv("CASE_VIDEO_GENERAL_API_KEY"):
        general_api_key_env = "CASE_VIDEO_GENERAL_API_KEY"
    elif general_auth_mode == "api-key":
        general_api_key_env = "AZURE_OPENAI_API_KEY"
    elif os.getenv("OPENAI_API_KEY"):
        general_api_key_env = "OPENAI_API_KEY"
    else:
        general_api_key_env = "AZURE_OPENAI_API_KEY"

    narration_route = ModelRoute(
        provider=os.getenv("CASE_VIDEO_NARRATION_PROVIDER", "azure_anthropic"),
        model=os.getenv("CASE_VIDEO_NARRATION_MODEL", "case-video-claude"),
        task_family="narration",
        endpoint=anthropic_endpoint,
        api_key_env=anthropic_api_key_env,
        api_version=anthropic_version,
        request_model=anthropic_deployment,
    )
    remotion_route = ModelRoute(
        provider=os.getenv("CASE_VIDEO_REMOTION_PROVIDER", "azure_anthropic"),
        model=os.getenv("CASE_VIDEO_REMOTION_MODEL", "case-video-claude"),
        task_family="remotion",
        endpoint=anthropic_endpoint,
        api_key_env=anthropic_api_key_env,
        api_version=anthropic_version,
        request_model=anthropic_deployment,
    )
    general_route = ModelRoute(
        provider=os.getenv("CASE_VIDEO_GENERAL_PROVIDER", "openai"),
        model=os.getenv("CASE_VIDEO_GENERAL_MODEL", "gpt-5.5"),
        task_family="general",
        base_url=general_base_url,
        api_key_env=general_api_key_env,
        request_model=os.getenv("CASE_VIDEO_GENERAL_REQUEST_MODEL", "gpt-5.5"),
        auth_mode=general_auth_mode,
    )

    return Settings(
        repo_root=repo_root,
        data_root=data_root,
        seed_projects_root=seed_root,
        redis_url=os.getenv("CASE_VIDEO_REDIS_URL", "redis://localhost:6379/0"),
        api_token=os.getenv("CASE_VIDEO_API_TOKEN"),
        dry_run=_bool_env("CASE_VIDEO_DRY_RUN", False),
        require_model_config=_bool_env("CASE_VIDEO_REQUIRE_MODEL_CONFIG", False),
        max_upload_bytes=_int_env("CASE_VIDEO_MAX_UPLOAD_BYTES", 200 * 1024 * 1024),
        max_upload_files=_int_env("CASE_VIDEO_MAX_UPLOAD_FILES", 25),
        max_archive_files=_int_env("CASE_VIDEO_MAX_ARCHIVE_FILES", 5_000),
        max_archive_expansion_bytes=_int_env(
            "CASE_VIDEO_MAX_ARCHIVE_EXPANSION_BYTES",
            500 * 1024 * 1024,
        ),
        max_archive_compression_ratio=_int_env("CASE_VIDEO_MAX_ARCHIVE_COMPRESSION_RATIO", 100),
        upload_ttl_seconds=_int_env("CASE_VIDEO_UPLOAD_TTL_SECONDS", 24 * 60 * 60),
        max_source_text_chars=_int_env("CASE_VIDEO_MAX_SOURCE_TEXT_CHARS", 2_000_000),
        max_external_excerpt_chars=_int_env("CASE_VIDEO_MAX_EXTERNAL_EXCERPT_CHARS", 4_000),
        command_timeout_seconds=_int_env("CASE_VIDEO_COMMAND_TIMEOUT_SECONDS", 24 * 60 * 60),
        narration_route=narration_route,
        remotion_route=remotion_route,
        general_route=general_route,
        deployment_mode=os.getenv("CASE_VIDEO_DEPLOYMENT_MODE", "single-node").strip().lower(),
        database_url=os.getenv(
            "CASE_VIDEO_DATABASE_URL",
            f"sqlite:///{repo_root / '.casevideo-data' / 'casevideo.db'}",
        ),
        database_pool_size=_int_env("CASE_VIDEO_DATABASE_POOL_SIZE", 10),
        object_store_backend=os.getenv("CASE_VIDEO_OBJECT_STORE_BACKEND", "local").strip().lower(),
        object_store_root=Path(
            os.getenv("CASE_VIDEO_OBJECT_STORE_ROOT", repo_root / ".casevideo-data" / "objects")
        ).resolve(),
        object_store_bucket=os.getenv("CASE_VIDEO_OBJECT_STORE_BUCKET", "case-video"),
        object_store_endpoint=os.getenv("CASE_VIDEO_OBJECT_STORE_ENDPOINT") or None,
        object_store_region=os.getenv("CASE_VIDEO_OBJECT_STORE_REGION", "us-east-1"),
        object_store_access_key_env=os.getenv(
            "CASE_VIDEO_OBJECT_STORE_ACCESS_KEY_ENV",
            "CASE_VIDEO_OBJECT_STORE_ACCESS_KEY",
        ),
        object_store_secret_key_env=os.getenv(
            "CASE_VIDEO_OBJECT_STORE_SECRET_KEY_ENV",
            "CASE_VIDEO_OBJECT_STORE_SECRET_KEY",
        ),
        object_store_signing_secret_env=os.getenv(
            "CASE_VIDEO_OBJECT_STORE_SIGNING_SECRET_ENV",
            "CASE_VIDEO_OBJECT_STORE_SIGNING_SECRET",
        ),
        default_tenant_id=os.getenv("CASE_VIDEO_DEFAULT_TENANT_ID", "ten_local"),
        default_tenant_name=os.getenv("CASE_VIDEO_DEFAULT_TENANT_NAME", "案例视频工作区"),
        default_user_id=os.getenv("CASE_VIDEO_DEFAULT_USER_ID", "usr_local"),
        default_role=os.getenv("CASE_VIDEO_DEFAULT_ROLE", "admin").strip().lower(),
        bootstrap_subject=os.getenv(
            "CASE_VIDEO_BOOTSTRAP_SUBJECT",
            os.getenv("CASE_VIDEO_DEFAULT_USER_ID", "usr_local"),
        ),
        bootstrap_email=os.getenv("CASE_VIDEO_BOOTSTRAP_EMAIL") or None,
        bootstrap_display_name=os.getenv("CASE_VIDEO_BOOTSTRAP_DISPLAY_NAME") or None,
        auth_mode=os.getenv("CASE_VIDEO_AUTH_MODE", "static-token").strip().lower(),
        oidc_issuer=os.getenv("CASE_VIDEO_OIDC_ISSUER") or None,
        oidc_audience=os.getenv("CASE_VIDEO_OIDC_AUDIENCE") or None,
        oidc_jwks_url=os.getenv("CASE_VIDEO_OIDC_JWKS_URL") or None,
        oidc_algorithms=_csv_env("CASE_VIDEO_OIDC_ALGORITHMS", ("RS256",)),
        oidc_require_nonce=_bool_env("CASE_VIDEO_OIDC_REQUIRE_NONCE", True),
        oidc_nonce_header=os.getenv("CASE_VIDEO_OIDC_NONCE_HEADER", "X-OIDC-Nonce"),
        oidc_authorization_endpoint=os.getenv("CASE_VIDEO_OIDC_AUTHORIZATION_ENDPOINT") or None,
        oidc_token_endpoint=os.getenv("CASE_VIDEO_OIDC_TOKEN_ENDPOINT") or None,
        oidc_client_id=os.getenv("CASE_VIDEO_OIDC_CLIENT_ID") or None,
        oidc_client_secret_env=os.getenv(
            "CASE_VIDEO_OIDC_CLIENT_SECRET_ENV",
            "CASE_VIDEO_OIDC_CLIENT_SECRET",
        ),
        oidc_scopes=_csv_env(
            "CASE_VIDEO_OIDC_SCOPES",
            ("openid", "profile", "email"),
        ),
        oidc_redirect_uri=os.getenv("CASE_VIDEO_OIDC_REDIRECT_URI") or None,
        session_cookie_name=os.getenv("CASE_VIDEO_SESSION_COOKIE_NAME", "casevideo_session"),
        session_state_cookie_name=os.getenv(
            "CASE_VIDEO_SESSION_STATE_COOKIE_NAME",
            "casevideo_oidc_state",
        ),
        session_secret_env=os.getenv(
            "CASE_VIDEO_SESSION_SECRET_ENV",
            "CASE_VIDEO_SESSION_SECRET",
        ),
        session_cookie_secure=_bool_env("CASE_VIDEO_SESSION_COOKIE_SECURE", True),
        session_max_age_seconds=_int_env("CASE_VIDEO_SESSION_MAX_AGE_SECONDS", 8 * 60 * 60),
        oidc_state_max_age_seconds=_int_env("CASE_VIDEO_OIDC_STATE_MAX_AGE_SECONDS", 10 * 60),
        reauth_max_age_seconds=_int_env("CASE_VIDEO_REAUTH_MAX_AGE_SECONDS", 5 * 60),
        service_account_scope=os.getenv(
            "CASE_VIDEO_SERVICE_ACCOUNT_SCOPE",
            "case-video.worker",
        ),
        tenant_header=os.getenv("CASE_VIDEO_TENANT_HEADER", "X-Tenant-ID"),
        cors_origins=_csv_env("CASE_VIDEO_CORS_ORIGINS"),
        csrf_trusted_origins=_csv_env("CASE_VIDEO_CSRF_TRUSTED_ORIGINS"),
        csrf_enabled=_bool_env("CASE_VIDEO_CSRF_ENABLED", True),
        csrf_cookie_name=os.getenv("CASE_VIDEO_CSRF_COOKIE_NAME", "casevideo_csrf"),
        csrf_header_name=os.getenv("CASE_VIDEO_CSRF_HEADER_NAME", "X-CSRF-Token"),
        upload_scanner_mode=os.getenv("CASE_VIDEO_UPLOAD_SCANNER", "clamav").strip().lower(),
        clamd_host=os.getenv("CASE_VIDEO_CLAMD_HOST", "clamav"),
        clamd_port=_int_env("CASE_VIDEO_CLAMD_PORT", 3310),
        clamd_timeout_seconds=_int_env("CASE_VIDEO_CLAMD_TIMEOUT_SECONDS", 60),
        redis_namespace=os.getenv("CASE_VIDEO_REDIS_NAMESPACE", "case-video"),
        worker_consumer_group=os.getenv("CASE_VIDEO_WORKER_CONSUMER_GROUP", "case-video-workers"),
        worker_heartbeat_seconds=_int_env("CASE_VIDEO_WORKER_HEARTBEAT_SECONDS", 15),
        worker_lease_seconds=_int_env("CASE_VIDEO_WORKER_LEASE_SECONDS", 90),
        worker_max_attempts=_int_env("CASE_VIDEO_WORKER_MAX_ATTEMPTS", 3),
        worker_workspace_root=Path(
            os.getenv(
                "CASE_VIDEO_WORKER_WORKSPACE_ROOT",
                repo_root / ".casevideo-data" / "worker-workspaces",
            )
        ).resolve(),
        signed_url_ttl_seconds=_int_env("CASE_VIDEO_SIGNED_URL_TTL_SECONDS", 15 * 60),
        orphan_ttl_seconds=_int_env("CASE_VIDEO_ORPHAN_TTL_SECONDS", 24 * 60 * 60),
        deletion_recovery_days=_int_env("CASE_VIDEO_DELETION_RECOVERY_DAYS", 7),
        succeeded_retention_days=_int_env("CASE_VIDEO_SUCCEEDED_RETENTION_DAYS", 90),
        failed_retention_days=_int_env("CASE_VIDEO_FAILED_RETENTION_DAYS", 30),
        audit_retention_days=_int_env("CASE_VIDEO_AUDIT_RETENTION_DAYS", 365),
        maintenance_interval_seconds=_int_env(
            "CASE_VIDEO_MAINTENANCE_INTERVAL_SECONDS",
            15 * 60,
        ),
        api_rate_limit_per_minute=_int_env("CASE_VIDEO_API_RATE_LIMIT_PER_MINUTE", 240),
        api_rate_limit_burst=_int_env("CASE_VIDEO_API_RATE_LIMIT_BURST", 40),
        rate_limit_backend=os.getenv("CASE_VIDEO_RATE_LIMIT_BACKEND", "memory").strip().lower(),
        metrics_enabled=_bool_env("CASE_VIDEO_METRICS_ENABLED", True),
        metrics_path=os.getenv("CASE_VIDEO_METRICS_PATH", "/internal/metrics"),
        structured_logs=_bool_env("CASE_VIDEO_STRUCTURED_LOGS", True),
        render_max_seconds=_int_env("CASE_VIDEO_RENDER_MAX_SECONDS", 45 * 60),
        render_term_grace_seconds=_int_env("CASE_VIDEO_RENDER_TERM_GRACE_SECONDS", 30),
        render_workspace_root=Path(
            os.getenv(
                "CASE_VIDEO_RENDER_WORKSPACE_ROOT",
                repo_root / ".casevideo-data" / "render-workspaces",
            )
        ).resolve(),
        render_engine_root=Path(
            os.getenv("CASE_VIDEO_RENDER_ENGINE_ROOT", repo_root / "engine" / "remotion")
        ).resolve(),
        render_engine_digest=os.getenv(
            "CASE_VIDEO_RENDER_ENGINE_DIGEST",
            "sha256:development-only-unpinned",
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
