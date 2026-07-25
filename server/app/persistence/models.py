from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    quotas: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    retention: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    oidc_subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Membership(Base):
    __tablename__ = "memberships"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        Index("ix_memberships_user", "user_id"),
    )


class Job(Base):
    __tablename__ = "jobs"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(120), nullable=False)
    input_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    route_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    engine_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "idempotency_key_hash", name="uq_jobs_tenant_idempotency"),
        Index("ix_jobs_tenant_status_updated", "tenant_id", "status", "updated_at"),
    )


class JobInput(Base):
    __tablename__ = "job_inputs"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    media_type: Mapped[str | None] = mapped_column(String(200))
    extraction_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    outbound_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
        Index("ix_job_inputs_job", "tenant_id", "job_id"),
    )


class Upload(Base):
    __tablename__ = "uploads"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    declared_media_type: Mapped[str | None] = mapped_column(String(200))
    detected_media_type: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    scan_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    bound_job_id: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "bound_job_id"],
            ["jobs.tenant_id", "jobs.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "object_key", name="uq_upload_object_key"),
        Index("ix_uploads_expiry", "tenant_id", "status", "expires_at"),
        Index("ix_uploads_bound_job", "tenant_id", "bound_job_id"),
    )


class JobStageRun(Base):
    __tablename__ = "job_stage_runs"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(120), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_cycle: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cycle_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    route_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_job_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paid_result_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "job_id", "stage", "attempt", name="uq_stage_attempt"),
        Index("ix_stage_runs_queue_status", "queue_name", "status", "created_at"),
        Index(
            "ix_stage_runs_idempotency",
            "tenant_id",
            "job_id",
            "stage",
            "input_hash",
            "route_snapshot_hash",
            "config_snapshot_hash",
        ),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
    )


class ArtifactRevision(Base):
    __tablename__ = "artifact_revisions"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(128))
    stage_run_id: Mapped[str | None] = mapped_column(String(128))
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "job_id", "domain", "revision_hash", name="uq_artifact_revision_hash"),
        Index("ix_artifact_revision_current", "tenant_id", "job_id", "domain", "is_current"),
    )


class ArtifactBlob(Base):
    __tablename__ = "artifact_blobs"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    logical_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    created_stage: Mapped[str] = mapped_column(String(120), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(40), nullable=False, default="clean")
    encryption: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            ["artifact_revisions.tenant_id", "artifact_revisions.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "object_key", name="uq_blob_object_key"),
        UniqueConstraint("tenant_id", "revision_id", "logical_name", name="uq_blob_logical_name"),
        Index("ix_artifact_blobs_job", "tenant_id", "job_id"),
    )


class ModelRun(Base):
    __tablename__ = "model_runs"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stage_run_id: Mapped[str | None] = mapped_column(String(128))
    task: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    route_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(255))
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
        Index("ix_model_runs_job_task", "tenant_id", "job_id", "task"),
    )


class Approval(Base):
    __tablename__ = "approvals"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gate: Mapped[str] = mapped_column(String(80), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
        Index("ix_approvals_gate_current", "tenant_id", "job_id", "gate", "is_current"),
    )


class CostLedger(Base):
    __tablename__ = "cost_ledger"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stage_run_id: Mapped[str | None] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USD")
    provider: Mapped[str | None] = mapped_column(String(80))
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    pricing_version: Mapped[str | None] = mapped_column(String(80))
    estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reference_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["jobs.tenant_id", "jobs.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "reference_id", "kind", name="uq_cost_reference_kind"),
        Index("ix_cost_job", "tenant_id", "job_id", "created_at"),
    )


class QuotaReservation(Base):
    __tablename__ = "quota_reservations"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str | None] = mapped_column(String(128))
    stage_run_id: Mapped[str | None] = mapped_column(String(128))
    dimension: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="consumption")
    window: Mapped[str] = mapped_column(String(32), nullable=False, default="monthly")
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reserved_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_amount: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    outcome: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[str] = mapped_column(String(160), nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["jobs.tenant_id", "jobs.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "dimension", "reference_id", name="uq_quota_reference"),
        Index("ix_quota_window", "tenant_id", "dimension", "status", "window_start", "window_end"),
        Index("ix_quota_job", "tenant_id", "job_id", "created_at"),
    )


class WorkerLease(Base):
    __tablename__ = "worker_leases"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    stage_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "stage_run_id"],
            ["job_stage_runs.tenant_id", "job_stage_runs.id"],
            ondelete="CASCADE",
        ),
        Index("ix_worker_lease_expiry", "lease_expires_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(160))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (Index("ix_audit_tenant_time", "tenant_id", "occurred_at"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    tenant_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_outbox_pending", "delivered_at", "created_at"),)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
