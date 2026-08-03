from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.app.core.config import load_settings
from server.app.persistence.bootstrap import bootstrap_repository
from server.app.persistence.database import Database
from server.app.persistence.object_store import LocalObjectStore, ObjectNotFound
from server.app.persistence.repository import PhaseCRepository, RepositoryNotFound
from server.app.workers.maintenance import MaintenanceService


def _manifest(job_id: str, status: str) -> dict[str, object]:
    return {
        "manifest_version": 2,
        "job_id": job_id,
        "project_name": job_id,
        "status": status,
        "display_status": status,
        "stage": "delivery.complete" if status == "succeeded" else "qa.delivery",
        "input_mode": "source",
        "approval_mode": "editorial",
        "model_routes": {
            "narration": {"provider": "azure_anthropic", "model": "case-video-claude"},
            "remotion": {"provider": "azure_anthropic", "model": "case-video-claude"},
            "general": {"provider": "openai", "model": "gpt-5.5"},
        },
        "budget": {"currency": "USD", "limit_micros": None, "spent_micros": 0},
    }


@pytest.fixture()
def phase_c_runtime(tmp_path: Path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase-c-ops.sqlite'}"
    database = Database(database_url)
    database.migrate()
    repository = PhaseCRepository(database)
    store = LocalObjectStore(tmp_path / "objects")
    settings = replace(
        load_settings(),
        deployment_mode="distributed",
        database_url=database_url,
        object_store_backend="local",
        object_store_root=store.root,
        default_tenant_id="ten_ops",
        default_tenant_name="Operations",
        default_user_id="usr_bootstrap",
        default_role="admin",
        bootstrap_subject="oidc|operator",
        bootstrap_email="operator@example.test",
        bootstrap_display_name="Operator",
        orphan_ttl_seconds=60,
        succeeded_retention_days=90,
        failed_retention_days=30,
        deletion_recovery_days=7,
        audit_retention_days=365,
    )
    try:
        yield database, repository, store, settings
    finally:
        database.dispose()


def test_bootstrap_is_idempotent_and_preserves_existing_governance_and_identity(
    phase_c_runtime,
) -> None:
    _, repository, _, settings = phase_c_runtime
    custom_quotas = {"active_jobs": 3, "monthly_cost_micros": 42}
    custom_retention = {"succeeded_days": 14, "audit_days": 730}
    custom_policy = {"change_ticket_required": True}
    repository.ensure_tenant(
        settings.default_tenant_id,
        name="Existing tenant",
        quotas=custom_quotas,
        retention=custom_retention,
        policy=custom_policy,
    )
    repository.ensure_tenant("ten_other", name="Other")
    existing = repository.ensure_user(
        "usr_existing",
        oidc_subject=settings.bootstrap_subject,
        email="old@example.test",
    )
    repository.set_membership("ten_other", str(existing["user_id"]), "viewer")

    first = bootstrap_repository(settings, repository)
    assert first.tenant_created is False
    assert first.user_created is False
    assert first.membership_created is True
    assert first.user_id == "usr_existing"
    assert first.role == "admin"
    tenant = repository.get_tenant(settings.default_tenant_id)
    assert tenant["name"] == "Existing tenant"
    assert tenant["quotas"] == custom_quotas
    assert tenant["retention"] == custom_retention
    assert tenant["policy"] == custom_policy

    repository.set_membership(settings.default_tenant_id, "usr_existing", "producer")
    second = bootstrap_repository(settings, repository)
    assert second.tenant_created is False
    assert second.user_created is False
    assert second.membership_created is False
    assert second.role == "producer"


def test_maintenance_applies_retention_legal_hold_and_orphan_cleanup(
    phase_c_runtime,
) -> None:
    database, repository, store, settings = phase_c_runtime
    now = datetime(2026, 7, 24, 10, tzinfo=timezone.utc)
    repository.ensure_tenant(
        "ten_ops",
        name="Operations",
        retention={
            "succeeded_days": 2,
            "failed_days": 1,
            "recovery_days": 1,
            "audit_days": 1,
            "orphan_ttl_seconds": 60,
        },
    )
    for job_id, status in (
        ("job_failed", "failed"),
        ("job_succeeded", "succeeded"),
        ("job_pinned", "failed"),
        ("job_held", "failed"),
        ("job_purge", "failed"),
    ):
        repository.create_job("ten_ops", _manifest(job_id, status))
    repository.set_job_protection("ten_ops", "job_pinned", pinned=True)
    repository.set_job_protection("ten_ops", "job_held", legal_hold=True)

    from server.app.persistence.models import AuditLog, CostLedger, Job

    with database.transaction() as session:
        for job_id in ("job_failed", "job_succeeded", "job_pinned", "job_held"):
            session.get(Job, ("ten_ops", job_id)).updated_at = now - timedelta(days=4)

    purge_key = "tenants/ten_ops/uploads/upl_purge/payload"
    store.put_bytes(purge_key, b"purge", media_type="application/octet-stream")
    repository.create_upload(
        "ten_ops",
        upload_id="upl_purge",
        filename="purge.bin",
        safe_name="purge.bin",
        declared_size_bytes=5,
        declared_media_type="application/octet-stream",
        declared_sha256=None,
        expires_at=now + timedelta(days=1),
    )
    repository.complete_upload(
        "ten_ops",
        "upl_purge",
        object_key=purge_key,
        size_bytes=5,
        sha256=store.head(purge_key).sha256,
        detected_media_type="application/octet-stream",
        scan_status="clean",
        now=now - timedelta(days=3),
    )
    repository.bind_upload("ten_ops", "upl_purge", "job_purge", now=now - timedelta(days=3))
    repository.mark_job_deleted(
        "ten_ops",
        "job_purge",
        recovery_days=1,
        now=now - timedelta(days=2),
    )

    expired_key = "tenants/ten_ops/uploads/upl_expired/payload"
    store.put_bytes(expired_key, b"expired", media_type="application/octet-stream")
    repository.create_upload(
        "ten_ops",
        upload_id="upl_expired",
        filename="expired.bin",
        safe_name="expired.bin",
        declared_size_bytes=7,
        declared_media_type="application/octet-stream",
        declared_sha256=None,
        expires_at=now - timedelta(seconds=1),
    )
    repository.complete_upload(
        "ten_ops",
        "upl_expired",
        object_key=expired_key,
        size_bytes=7,
        sha256=store.head(expired_key).sha256,
        detected_media_type="application/octet-stream",
        scan_status="clean",
        now=now - timedelta(hours=1),
    )

    repository.reserve_cost(
        "ten_ops",
        "job_failed",
        stage_run_id=None,
        amount_micros=10,
        provider="openai",
        usage={},
        pricing_version="test",
        reference_id="old-normal",
        now=now - timedelta(days=3),
    )
    repository.reserve_cost(
        "ten_ops",
        "job_held",
        stage_run_id=None,
        amount_micros=20,
        provider="azure_anthropic",
        usage={},
        pricing_version="test",
        reference_id="old-held",
        now=now - timedelta(days=3),
    )
    repository.audit(
        "ten_ops",
        actor_id="usr_test",
        action="job.old_normal",
        resource_type="job",
        resource_id="job_failed",
        result="succeeded",
    )
    repository.audit(
        "ten_ops",
        actor_id="usr_test",
        action="job.old_held",
        resource_type="job",
        resource_id="job_held",
        result="succeeded",
    )
    with database.transaction() as session:
        for row in session.query(AuditLog).filter(AuditLog.action.like("job.old_%")):
            row.occurred_at = now - timedelta(days=3)
        for row in session.query(CostLedger):
            row.created_at = now - timedelta(days=3)

    old_orphan = "tenants/ten_ops/orphans/old"
    recent_orphan = "tenants/ten_ops/orphans/recent"
    store.put_bytes(old_orphan, b"old", media_type="application/octet-stream")
    store.put_bytes(recent_orphan, b"recent", media_type="application/octet-stream")
    old_timestamp = (now - timedelta(minutes=2)).timestamp()
    recent_timestamp = (now - timedelta(seconds=10)).timestamp()
    os.utime(store.root / old_orphan, (old_timestamp, old_timestamp))
    os.utime(store.root / recent_orphan, (recent_timestamp, recent_timestamp))

    report = MaintenanceService(settings, repository, store).run_once(now=now)
    tenant_report = report.tenants[0]
    assert tenant_report.expired_uploads == 1
    assert tenant_report.hidden_jobs == 2
    assert tenant_report.purged_jobs == 1
    assert tenant_report.pruned_audit_rows == 1
    assert tenant_report.pruned_cost_rows == 1
    assert report.orphan_objects_deleted == 1
    assert report.failure_count == 0

    with pytest.raises(ObjectNotFound):
        store.head(expired_key)
    with pytest.raises(ObjectNotFound):
        store.head(purge_key)
    with pytest.raises(ObjectNotFound):
        store.head(old_orphan)
    assert store.head(recent_orphan).size_bytes == 6
    with pytest.raises(RepositoryNotFound):
        repository.get_upload("ten_ops", "upl_expired", include_expired=True)
    with pytest.raises(RepositoryNotFound):
        repository.get_upload("ten_ops", "upl_purge", include_expired=True)

    assert repository.get_job("ten_ops", "job_failed", include_deleted=True)["deleted_at"]
    assert repository.get_job("ten_ops", "job_succeeded", include_deleted=True)["deleted_at"]
    assert repository.get_job("ten_ops", "job_pinned")["deleted_at"] is None
    assert repository.get_job("ten_ops", "job_held")["deleted_at"] is None
    assert repository.cost_ledger("ten_ops", "job_failed") == []
    assert len(repository.cost_ledger("ten_ops", "job_held")) == 1
    assert repository.list_audit("ten_ops", action="job.old_normal") == []
    assert len(repository.list_audit("ten_ops", action="job.old_held")) == 1
    assert len(repository.list_audit("ten_ops", action="retention.cycle")) == 1
