from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from server.app.core.config import Settings, load_settings
from server.app.persistence.database import Database
from server.app.persistence.repository import PhaseCRepository, RepositoryNotFound


@dataclass(frozen=True)
class BootstrapReport:
    tenant_id: str
    tenant_created: bool
    user_id: str
    user_created: bool
    membership_created: bool
    role: str


def default_quotas() -> dict[str, int]:
    return {
        "active_jobs": 20,
        "upload_bytes": 10 * 1024 * 1024 * 1024,
        "upload_files": 100,
        "render_concurrency": 1,
    }


def default_retention(settings: Settings) -> dict[str, int]:
    return {
        "succeeded_days": settings.succeeded_retention_days,
        "failed_days": settings.failed_retention_days,
        "recovery_days": settings.deletion_recovery_days,
        "audit_days": settings.audit_retention_days,
        "upload_ttl_seconds": settings.upload_ttl_seconds,
        "orphan_ttl_seconds": settings.orphan_ttl_seconds,
    }


def default_policy() -> dict[str, object]:
    return {
        "model_routes_locked": True,
        "require_clean_upload_scan": True,
        "allow_cross_route_fallback": False,
        "default_approval_mode": "full",
    }


def bootstrap_repository(settings: Settings, repository: PhaseCRepository) -> BootstrapReport:
    try:
        repository.get_tenant(settings.default_tenant_id)
        tenant_created = False
    except RepositoryNotFound:
        repository.ensure_tenant(
            settings.default_tenant_id,
            name=settings.default_tenant_name,
            quotas=default_quotas(),
            retention=default_retention(settings),
            policy=default_policy(),
        )
        tenant_created = True

    existing_identity = repository.find_user_by_subject(settings.bootstrap_subject)
    existing_users = {
        item["oidc_subject"]: item
        for item in repository.list_memberships(settings.default_tenant_id)
    }
    existing = existing_users.get(settings.bootstrap_subject)
    user = repository.ensure_user(
        settings.default_user_id,
        oidc_subject=settings.bootstrap_subject,
        email=settings.bootstrap_email,
        display_name=settings.bootstrap_display_name,
    )
    user_created = existing_identity is None
    membership_created = False
    if existing is None:
        repository.set_membership(
            settings.default_tenant_id,
            str(user["user_id"]),
            settings.default_role,
        )
        membership_created = True

    return BootstrapReport(
        tenant_id=settings.default_tenant_id,
        tenant_created=tenant_created,
        user_id=str(user["user_id"]),
        user_created=user_created,
        membership_created=membership_created,
        role=str(existing["role"] if existing is not None else settings.default_role),
    )


def main() -> None:
    settings = load_settings()
    if settings.deployment_mode != "distributed":
        raise RuntimeError("bootstrap requires CASE_VIDEO_DEPLOYMENT_MODE=distributed")
    database = Database.from_settings(settings)
    try:
        database.check_schema()
        report = bootstrap_repository(settings, PhaseCRepository(database))
        print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
