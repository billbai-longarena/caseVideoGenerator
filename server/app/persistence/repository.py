from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from server.app.persistence.database import Database
from server.app.persistence.models import (
    Approval,
    ArtifactBlob,
    ArtifactRevision,
    AuditLog,
    CostLedger,
    Job,
    JobEvent,
    JobInput,
    JobStageRun,
    Membership,
    ModelRun,
    OutboxEvent,
    QuotaReservation,
    Tenant,
    Upload,
    User,
    WorkerLease,
    utc_now,
)


ROLE_ORDER = {"viewer": 0, "editor": 1, "producer": 2, "admin": 3}
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "canceled", "deleted"}
ACTIVE_STAGE_STATUSES = {"queued", "running"}
QUOTA_MODES = {"consumption", "capacity"}
QUOTA_WINDOWS = {"daily", "monthly", "lifetime", "capacity"}
QUOTA_OUTCOMES = {"succeeded", "failed", "canceled", "superseded", "released"}


_tenant_quota_locks_guard = threading.Lock()
_tenant_quota_locks: dict[str, threading.RLock] = {}


def _tenant_quota_lock(tenant_id: str) -> threading.RLock:
    """Serialize quota checks for SQLite tests and single-process fallback.

    PostgreSQL still uses a row lock and remains the production authority. The
    process lock closes SQLite's lack of ``SELECT ... FOR UPDATE`` semantics so
    the same race tests are meaningful in CI.
    """

    with _tenant_quota_locks_guard:
        return _tenant_quota_locks.setdefault(tenant_id, threading.RLock())


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class RepositoryError(RuntimeError):
    code = "repository_error"


class RepositoryNotFound(RepositoryError):
    code = "not_found"


class RepositoryConflict(RepositoryError):
    code = "revision_conflict"


class IdempotencyConflict(RepositoryConflict):
    code = "idempotency_conflict"


class LeaseConflict(RepositoryConflict):
    code = "lease_conflict"


class QuotaExceeded(RepositoryConflict):
    code = "quota_exceeded"


class BudgetApprovalRequired(RepositoryConflict):
    code = "budget_approval_required"


@dataclass(frozen=True)
class StageIdentity:
    tenant_id: str
    job_id: str
    stage: str
    input_hash: str
    route_snapshot_hash: str
    config_snapshot_hash: str


@dataclass(frozen=True)
class BlobRegistration:
    logical_name: str
    object_key: str
    size_bytes: int
    sha256: str
    media_type: str
    scan_status: str = "clean"
    encryption: dict[str, Any] | None = None


@dataclass(frozen=True)
class ArtifactBundleRegistration:
    domain: str
    revision_id: str
    parent_id: str | None
    created_by: str
    blobs: tuple[BlobRegistration, ...]
    revision_hash: str
    make_current: bool = True


@dataclass(frozen=True)
class ModelRunRegistration:
    id: str
    task: str
    provider: str
    model: str
    route_snapshot: dict[str, Any]
    prompt_version: str
    schema_version: str
    provider_call_id: str | None = None
    usage: dict[str, Any] | None = None
    cost_micros: int = 0
    status: str = "succeeded"


@dataclass(frozen=True)
class JobInputRegistration:
    input_id: str
    kind: str
    object_key: str | None
    sha256: str | None
    size_bytes: int | None
    media_type: str | None
    upload_id: str | None = None
    extraction_status: str = "pending"
    outbound_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class PhaseCRepository:
    """Tenant-scoped repository for all Phase C authoritative metadata.

    Every business lookup takes a tenant ID and includes it in the SQL
    predicate. Callers cannot retrieve a row by globally enumerable ID alone.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    # -- Identity and tenancy -------------------------------------------------

    def ensure_tenant(
        self,
        tenant_id: str,
        *,
        name: str | None = None,
        quotas: dict[str, Any] | None = None,
        retention: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None:
                tenant = Tenant(
                    id=tenant_id,
                    name=name or tenant_id,
                    quotas=copy.deepcopy(quotas or {}),
                    retention=copy.deepcopy(retention or {}),
                    policy=copy.deepcopy(policy or {}),
                )
                session.add(tenant)
            else:
                if name is not None:
                    tenant.name = name
                if quotas is not None:
                    tenant.quotas = copy.deepcopy(quotas)
                if retention is not None:
                    tenant.retention = copy.deepcopy(retention)
                if policy is not None:
                    tenant.policy = copy.deepcopy(policy)
            session.flush()
            return self._tenant_dict(tenant)

    def ensure_user(
        self,
        user_id: str,
        *,
        oidc_subject: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            user = session.scalar(select(User).where(User.oidc_subject == oidc_subject))
            if user is None:
                user = User(
                    id=user_id,
                    oidc_subject=oidc_subject,
                    email=email,
                    display_name=display_name,
                )
                session.add(user)
            else:
                user.email = email or user.email
                user.display_name = display_name or user.display_name
            session.flush()
            return self._user_dict(user)

    def find_user_by_subject(self, oidc_subject: str) -> dict[str, Any] | None:
        """Return the globally unique OIDC identity without changing membership."""

        with self.database.session() as session:
            user = session.scalar(select(User).where(User.oidc_subject == oidc_subject))
            return None if user is None else self._user_dict(user)

    def set_membership(self, tenant_id: str, user_id: str, role: str, *, disabled: bool = False) -> None:
        if role not in ROLE_ORDER:
            raise RepositoryError(f"unsupported role: {role}")
        with self.database.transaction() as session:
            if session.get(Tenant, tenant_id) is None or session.get(User, user_id) is None:
                raise RepositoryNotFound("tenant or user not found")
            membership = session.get(Membership, (tenant_id, user_id))
            if membership is None:
                membership = Membership(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    role=role,
                    disabled=disabled,
                )
                session.add(membership)
            else:
                membership.role = role
                membership.disabled = disabled

    def memberships_for_subject(self, oidc_subject: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.execute(
                select(Membership, User, Tenant)
                .join(User, User.id == Membership.user_id)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(
                    User.oidc_subject == oidc_subject,
                    User.disabled.is_(False),
                    Membership.disabled.is_(False),
                    Tenant.status == "active",
                )
            ).all()
            return [
                {
                    "tenant_id": membership.tenant_id,
                    "user_id": membership.user_id,
                    "role": membership.role,
                    "tenant_name": tenant.name,
                    "email": user.email,
                    "display_name": user.display_name,
                }
                for membership, user, tenant in rows
            ]

    def get_tenant(self, tenant_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            return self._tenant_dict(self._require_tenant(session, tenant_id))

    def list_tenants(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        """List tenant metadata for trusted control-plane workers.

        Public request paths remain tenant-scoped.  This unscoped lookup is
        intentionally kept on the repository control plane so retention and
        recovery workers can service every tenant without accepting a tenant
        identifier from an external caller.
        """

        with self.database.session() as session:
            statement = select(Tenant)
            if active_only:
                statement = statement.where(Tenant.status == "active")
            rows = session.scalars(statement.order_by(Tenant.id))
            return [self._tenant_dict(row) for row in rows]

    def update_tenant_governance(
        self,
        tenant_id: str,
        *,
        quotas: dict[str, Any] | None = None,
        retention: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            tenant = self._require_tenant(session, tenant_id, for_update=True)
            if quotas is not None:
                tenant.quotas = copy.deepcopy(quotas)
            if retention is not None:
                tenant.retention = copy.deepcopy(retention)
            if policy is not None:
                tenant.policy = copy.deepcopy(policy)
            tenant.updated_at = utc_now()
            session.flush()
            return self._tenant_dict(tenant)

    def list_memberships(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_tenant(session, tenant_id)
            rows = session.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.tenant_id == tenant_id)
                .order_by(User.display_name, User.email, User.id)
            ).all()
            return [
                {
                    "tenant_id": membership.tenant_id,
                    "user_id": membership.user_id,
                    "oidc_subject": user.oidc_subject,
                    "email": user.email,
                    "display_name": user.display_name,
                    "role": membership.role,
                    "disabled": membership.disabled or user.disabled,
                }
                for membership, user in rows
            ]

    def membership_for_subject(self, tenant_id: str, oidc_subject: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.memberships_for_subject(oidc_subject)
                if item["tenant_id"] == tenant_id
            ),
            None,
        )

    # -- Jobs, snapshots, inputs, and events ---------------------------------

    def create_job(
        self,
        tenant_id: str,
        manifest: dict[str, Any],
        *,
        request_hash: str | None = None,
        config_snapshot: dict[str, Any] | None = None,
        engine_snapshot: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        manifest_copy = copy.deepcopy(manifest)
        idempotency_hash = manifest_copy.get("idempotency_key_hash")
        with self.database.transaction() as session:
            self._require_tenant(session, tenant_id)
            if idempotency_hash:
                existing = session.scalar(
                    select(Job).where(
                        Job.tenant_id == tenant_id,
                        Job.idempotency_key_hash == idempotency_hash,
                    )
                )
                if existing is not None:
                    if request_hash and existing.request_hash and existing.request_hash != request_hash:
                        raise IdempotencyConflict(
                            "idempotency key was reused with a different request"
                        )
                    return self._job_snapshot(existing), False
            if session.get(Job, (tenant_id, manifest_copy["job_id"])) is not None:
                raise RepositoryConflict("job already exists")
            job = Job(
                tenant_id=tenant_id,
                id=manifest_copy["job_id"],
                project_name=manifest_copy["project_name"],
                status=manifest_copy["status"],
                stage=manifest_copy["stage"],
                input_mode=manifest_copy.get("input_mode", "project"),
                approval_mode=manifest_copy.get("approval_mode", "editorial"),
                manifest=manifest_copy,
                manifest_sha256=sha256_json(manifest_copy),
                idempotency_key_hash=idempotency_hash,
                request_hash=request_hash,
                route_snapshot=copy.deepcopy(manifest_copy.get("model_routes", {})),
                config_snapshot=copy.deepcopy(config_snapshot or self._config_snapshot_from_manifest(manifest_copy)),
                engine_snapshot=copy.deepcopy(engine_snapshot or {}),
                created_at=self._parse_time(manifest_copy.get("created_at")) or utc_now(),
                updated_at=self._parse_time(manifest_copy.get("updated_at")) or utc_now(),
            )
            session.add(job)
            self._add_outbox(
                session,
                tenant_id,
                "job.created",
                "job",
                job.id,
                {"tenant_id": tenant_id, "job_id": job.id, "row_version": 1},
            )
            session.flush()
            return self._job_snapshot(job), True

    def create_job_bundle(
        self,
        tenant_id: str,
        manifest: dict[str, Any],
        *,
        inputs: Sequence[JobInputRegistration],
        request_hash: str | None,
        actor_id: str,
        request_id: str | None = None,
        initial_stage: str = "ingest.validate",
        queue_name: str = "planning",
        priority: str = "normal",
        config_snapshot: dict[str, Any] | None = None,
        engine_snapshot: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Create the complete authoritative job envelope in one transaction.

        API instances use this boundary after bytes have passed quarantine and
        reached immutable object storage. A failure at any validation, quota,
        or persistence step rolls back the job, input bindings, first stage,
        outbox records, event, reservation, and audit record together.
        """

        manifest_copy = copy.deepcopy(manifest)
        idempotency_hash = manifest_copy.get("idempotency_key_hash")
        current = as_utc(now or utc_now())
        config_copy = copy.deepcopy(
            config_snapshot or self._config_snapshot_from_manifest(manifest_copy)
        )
        engine_copy = copy.deepcopy(engine_snapshot or {})
        registrations = tuple(inputs)
        if not registrations:
            raise RepositoryError("at least one job input is required")
        input_ids = [item.input_id for item in registrations]
        if len(input_ids) != len(set(input_ids)):
            raise RepositoryConflict("job input IDs must be unique")
        upload_ids = [item.upload_id for item in registrations if item.upload_id]
        if len(upload_ids) != len(set(upload_ids)):
            raise RepositoryConflict("an upload cannot be bound more than once")

        sqlite_quota_guard = (
            _tenant_quota_lock(tenant_id)
            if self.database.engine.dialect.name == "sqlite"
            else nullcontext()
        )
        with sqlite_quota_guard:
            with self.database.transaction() as session:
                tenant = self._require_tenant(session, tenant_id)
                if idempotency_hash:
                    existing = session.scalar(
                        select(Job).where(
                            Job.tenant_id == tenant_id,
                            Job.idempotency_key_hash == idempotency_hash,
                        )
                    )
                    if existing is not None:
                        if request_hash and existing.request_hash and existing.request_hash != request_hash:
                            raise IdempotencyConflict(
                                "idempotency key was reused with a different request"
                            )
                        run = session.scalar(
                            select(JobStageRun)
                            .where(
                                JobStageRun.tenant_id == tenant_id,
                                JobStageRun.job_id == existing.id,
                                JobStageRun.stage == initial_stage,
                            )
                            .order_by(JobStageRun.attempt)
                            .limit(1)
                        )
                        if run is None:
                            raise RepositoryConflict(
                                "idempotent job exists without its initial stage"
                            )
                        return self._job_snapshot(existing), self._stage_dict(run), False

                job_id = str(manifest_copy["job_id"])
                if session.get(Job, (tenant_id, job_id)) is not None:
                    raise RepositoryConflict("job already exists")

                uploads: dict[str, Upload] = {}
                for upload_id in upload_ids:
                    upload = session.scalar(
                        select(Upload)
                        .where(Upload.tenant_id == tenant_id, Upload.id == upload_id)
                        .with_for_update()
                    )
                    if (
                        upload is None
                        or (upload.bound_job_id is None and as_utc(upload.expires_at) <= current)
                    ):
                        raise RepositoryNotFound("upload not found")
                    if upload.status != "complete" or upload.scan_status != "clean":
                        raise RepositoryConflict("upload has not passed quarantine scanning")
                    if upload.bound_job_id is not None:
                        raise RepositoryConflict("upload is already bound to another job")
                    uploads[upload_id] = upload

                for registration in registrations:
                    if registration.upload_id is None:
                        continue
                    upload = uploads[registration.upload_id]
                    if (
                        registration.object_key != upload.object_key
                        or registration.sha256 != upload.sha256
                        or registration.size_bytes != upload.size_bytes
                    ):
                        raise RepositoryConflict("job input does not match quarantined upload")

                job = Job(
                    tenant_id=tenant_id,
                    id=job_id,
                    project_name=manifest_copy["project_name"],
                    status=manifest_copy["status"],
                    stage=manifest_copy["stage"],
                    input_mode=manifest_copy.get("input_mode", "source"),
                    approval_mode=manifest_copy.get("approval_mode", "editorial"),
                    manifest=manifest_copy,
                    manifest_sha256=sha256_json(manifest_copy),
                    idempotency_key_hash=idempotency_hash,
                    request_hash=request_hash,
                    route_snapshot=copy.deepcopy(manifest_copy.get("model_routes", {})),
                    config_snapshot=config_copy,
                    engine_snapshot=engine_copy,
                    event_sequence=1,
                    created_at=self._parse_time(manifest_copy.get("created_at")) or current,
                    updated_at=self._parse_time(manifest_copy.get("updated_at")) or current,
                )
                session.add(job)
                session.flush()

                for registration in registrations:
                    session.add(
                        JobInput(
                            tenant_id=tenant_id,
                            id=registration.input_id,
                            job_id=job_id,
                            kind=registration.kind,
                            object_key=registration.object_key,
                            sha256=registration.sha256,
                            size_bytes=registration.size_bytes,
                            media_type=registration.media_type,
                            extraction_status=registration.extraction_status,
                            outbound_policy=copy.deepcopy(registration.outbound_policy or {}),
                            metadata_json=copy.deepcopy(registration.metadata or {}),
                        )
                    )
                    if registration.upload_id:
                        upload = uploads[registration.upload_id]
                        upload.bound_job_id = job_id
                        upload.bound_at = current
                        for dimension, suffix in (
                            ("upload_bytes", "bytes"),
                            ("upload_files", "files"),
                        ):
                            upload_quota = session.scalar(
                                select(QuotaReservation)
                                .where(
                                    QuotaReservation.tenant_id == tenant_id,
                                    QuotaReservation.dimension == dimension,
                                    QuotaReservation.reference_id
                                    == f"upload:{registration.upload_id}:{suffix}",
                                )
                                .with_for_update()
                            )
                            if upload_quota is not None and upload_quota.status == "active":
                                upload_quota.actual_amount = 0
                                upload_quota.status = "released"
                                upload_quota.outcome = "released"
                                upload_quota.settled_at = current

                input_hash = sha256_json(
                    [
                        {
                            "input_id": item.input_id,
                            "kind": item.kind,
                            "object_key": item.object_key,
                            "sha256": item.sha256,
                            "size_bytes": item.size_bytes,
                            "media_type": item.media_type,
                            "outbound_policy": item.outbound_policy or {},
                        }
                        for item in registrations
                    ]
                )
                run = JobStageRun(
                    tenant_id=tenant_id,
                    id=new_id("run"),
                    job_id=job_id,
                    stage=initial_stage,
                    queue_name=queue_name,
                    attempt=1,
                    retry_cycle=0,
                    cycle_attempt=1,
                    input_hash=input_hash,
                    route_snapshot_hash=sha256_json(job.route_snapshot),
                    config_snapshot_hash=sha256_json(config_copy),
                    expected_job_version=1,
                    status="queued",
                    priority=priority,
                    created_at=current,
                )
                session.add(run)

                tenant = self._lock_tenant_quota(session, tenant_id, tenant)
                active_limit = self._quota_limit(tenant.quotas, "active_jobs", "capacity")
                active_committed = self._quota_committed(
                    session,
                    tenant_id,
                    "active_jobs",
                    "capacity",
                    None,
                    None,
                    current,
                )
                if active_limit is not None and active_committed + 1 > active_limit:
                    raise QuotaExceeded(
                        f"tenant quota active_jobs would be exceeded: {active_committed + 1}>{active_limit}"
                    )
                session.add(
                    QuotaReservation(
                        tenant_id=tenant_id,
                        id=new_id("quota"),
                        job_id=job_id,
                        dimension="active_jobs",
                        mode="capacity",
                        window="capacity",
                        window_start=None,
                        window_end=None,
                        reserved_amount=1,
                        status="active",
                        reference_id=f"job:{job_id}:active",
                        usage={"source": "job.create"},
                        created_at=current,
                    )
                )

                event = JobEvent(
                    tenant_id=tenant_id,
                    job_id=job_id,
                    sequence=1,
                    event_type="job.created",
                    stage=initial_stage,
                    message="任务已创建并进入输入校验队列",
                    payload={"stage_run_id": run.id, "queue": queue_name},
                    occurred_at=current,
                )
                session.add(event)
                self._add_outbox(
                    session,
                    tenant_id,
                    "job.created",
                    "job",
                    job_id,
                    {"tenant_id": tenant_id, "job_id": job_id, "row_version": 1},
                )
                self._add_outbox(
                    session,
                    tenant_id,
                    "job.event",
                    "job",
                    job_id,
                    {
                        "tenant_id": tenant_id,
                        "job_id": job_id,
                        "sequence": 1,
                        "event_type": "job.created",
                    },
                )
                self._enqueue_stage_outbox(session, run)
                session.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        id=new_id("aud"),
                        actor_id=actor_id,
                        action="job.create",
                        resource_type="job",
                        resource_id=job_id,
                        result="succeeded",
                        request_id=request_id,
                        payload={
                            "input_count": len(registrations),
                            "upload_count": len(upload_ids),
                            "initial_stage": initial_stage,
                        },
                        occurred_at=current,
                    )
                )
                session.flush()
                return self._job_snapshot(job), self._stage_dict(run), True

    def add_job_input(
        self,
        tenant_id: str,
        job_id: str,
        *,
        input_id: str,
        kind: str,
        object_key: str | None,
        sha256: str | None,
        size_bytes: int | None,
        media_type: str | None,
        extraction_status: str = "pending",
        outbound_policy: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.database.transaction() as session:
            self._require_job(session, tenant_id, job_id)
            session.add(
                JobInput(
                    tenant_id=tenant_id,
                    id=input_id,
                    job_id=job_id,
                    kind=kind,
                    object_key=object_key,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    media_type=media_type,
                    extraction_status=extraction_status,
                    outbound_policy=copy.deepcopy(outbound_policy or {}),
                    metadata_json=copy.deepcopy(metadata or {}),
                )
            )

    def list_job_inputs(self, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id, include_deleted=True)
            rows = session.scalars(
                select(JobInput)
                .where(JobInput.tenant_id == tenant_id, JobInput.job_id == job_id)
                .order_by(JobInput.created_at, JobInput.id)
            )
            return [self._job_input_dict(row) for row in rows]

    # -- Quarantined uploads -------------------------------------------------

    def create_upload(
        self,
        tenant_id: str,
        *,
        upload_id: str,
        filename: str,
        safe_name: str,
        declared_size_bytes: int,
        declared_media_type: str | None,
        declared_sha256: str | None,
        expires_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if declared_size_bytes <= 0:
            raise RepositoryError("upload size must be positive")
        with self.database.transaction() as session:
            self._require_tenant(session, tenant_id)
            if session.get(Upload, (tenant_id, upload_id)) is not None:
                raise RepositoryConflict("upload already exists")
            upload = Upload(
                tenant_id=tenant_id,
                id=upload_id,
                filename=filename,
                safe_name=safe_name,
                declared_size_bytes=declared_size_bytes,
                declared_media_type=declared_media_type,
                status="pending",
                scan_status="pending",
                expires_at=as_utc(expires_at),
                metadata_json={
                    **copy.deepcopy(metadata or {}),
                    **({"declared_sha256": declared_sha256} if declared_sha256 else {}),
                },
            )
            session.add(upload)
            session.flush()
            return self._upload_dict(upload)

    def get_upload(
        self,
        tenant_id: str,
        upload_id: str,
        *,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = as_utc(now or utc_now())
        with self.database.session() as session:
            upload = session.get(Upload, (tenant_id, upload_id))
            if upload is None:
                raise RepositoryNotFound("upload not found")
            if (
                not include_expired
                and upload.bound_job_id is None
                and as_utc(upload.expires_at) <= current
            ):
                raise RepositoryNotFound("upload not found")
            return self._upload_dict(upload)

    def list_uploads(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        bound: bool | None = None,
        include_expired: bool = False,
        limit: int = 200,
        offset: int = 0,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        current = as_utc(now or utc_now())
        with self.database.session() as session:
            self._require_tenant(session, tenant_id)
            statement = select(Upload).where(Upload.tenant_id == tenant_id)
            if status is not None:
                statement = statement.where(Upload.status == status)
            if bound is True:
                statement = statement.where(Upload.bound_job_id.is_not(None))
            elif bound is False:
                statement = statement.where(Upload.bound_job_id.is_(None))
            if not include_expired:
                statement = statement.where(
                    or_(Upload.bound_job_id.is_not(None), Upload.expires_at > current)
                )
            statement = (
                statement.order_by(Upload.created_at.desc(), Upload.id.desc())
                .limit(max(1, min(limit, 1000)))
                .offset(max(offset, 0))
            )
            return [self._upload_dict(row) for row in session.scalars(statement)]

    def complete_upload(
        self,
        tenant_id: str,
        upload_id: str,
        *,
        object_key: str,
        size_bytes: int,
        sha256: str,
        detected_media_type: str,
        scan_status: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            upload = session.scalar(
                select(Upload)
                .where(Upload.tenant_id == tenant_id, Upload.id == upload_id)
                .with_for_update()
            )
            if upload is None or (upload.bound_job_id is None and as_utc(upload.expires_at) <= current):
                raise RepositoryNotFound("upload not found")
            if upload.status == "complete":
                if upload.sha256 != sha256 or upload.size_bytes != size_bytes or upload.object_key != object_key:
                    raise RepositoryConflict("completed upload cannot be replaced with different content")
                return self._upload_dict(upload)
            if upload.status != "pending":
                raise RepositoryConflict(f"upload is not writable in status {upload.status}")
            if size_bytes != upload.declared_size_bytes:
                raise RepositoryConflict("uploaded size does not match the declared size")
            declared_sha = upload.metadata_json.get("declared_sha256")
            if declared_sha and declared_sha != sha256:
                raise RepositoryConflict("uploaded sha256 does not match the declared sha256")
            upload.object_key = object_key
            upload.size_bytes = size_bytes
            upload.sha256 = sha256
            upload.detected_media_type = detected_media_type
            upload.scan_status = scan_status
            upload.status = "complete" if scan_status == "clean" else "quarantined"
            upload.completed_at = current
            session.flush()
            return self._upload_dict(upload)

    def bind_upload(
        self,
        tenant_id: str,
        upload_id: str,
        job_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            self._require_job(session, tenant_id, job_id)
            upload = session.scalar(
                select(Upload)
                .where(Upload.tenant_id == tenant_id, Upload.id == upload_id)
                .with_for_update()
            )
            if upload is None or (upload.bound_job_id is None and as_utc(upload.expires_at) <= current):
                raise RepositoryNotFound("upload not found")
            if upload.status != "complete" or upload.scan_status != "clean":
                raise RepositoryConflict("upload has not passed quarantine scanning")
            if upload.bound_job_id not in {None, job_id}:
                raise RepositoryConflict("upload is already bound to another job")
            upload.bound_job_id = job_id
            upload.bound_at = current
            session.flush()
            return self._upload_dict(upload)

    def delete_upload(self, tenant_id: str, upload_id: str) -> str | None:
        with self.database.transaction() as session:
            upload = session.get(Upload, (tenant_id, upload_id))
            if upload is None:
                raise RepositoryNotFound("upload not found")
            if upload.bound_job_id is not None:
                raise RepositoryConflict("bound upload cannot be deleted independently")
            object_key = upload.object_key
            session.delete(upload)
            return object_key

    def expire_unbound_uploads(self, tenant_id: str, *, now: datetime) -> list[str]:
        current = as_utc(now)
        object_keys: list[str] = []
        with self.database.transaction() as session:
            uploads = list(
                session.scalars(
                    select(Upload)
                    .where(
                        Upload.tenant_id == tenant_id,
                        Upload.bound_job_id.is_(None),
                        Upload.expires_at <= current,
                    )
                    .with_for_update()
                )
            )
            for upload in uploads:
                if upload.object_key:
                    object_keys.append(upload.object_key)
                for dimension, suffix in (("upload_bytes", "bytes"), ("upload_files", "files")):
                    reservation = session.scalar(
                        select(QuotaReservation)
                        .where(
                            QuotaReservation.tenant_id == tenant_id,
                            QuotaReservation.dimension == dimension,
                            QuotaReservation.reference_id == f"upload:{upload.id}:{suffix}",
                        )
                        .with_for_update()
                    )
                    if reservation is not None and reservation.status == "active":
                        reservation.actual_amount = 0
                        reservation.status = "released"
                        reservation.outcome = "released"
                        reservation.settled_at = current
                session.delete(upload)
        return object_keys

    def get_job(self, tenant_id: str, job_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
        with self.database.session() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=include_deleted)
            return self._job_snapshot(job)

    def find_idempotent_job(
        self,
        tenant_id: str,
        idempotency_key_hash: str,
        *,
        request_hash: str | None = None,
    ) -> dict[str, Any] | None:
        with self.database.session() as session:
            job = session.scalar(
                select(Job).where(
                    Job.tenant_id == tenant_id,
                    Job.idempotency_key_hash == idempotency_key_hash,
                    Job.deleted_at.is_(None),
                )
            )
            if job is None:
                return None
            if request_hash and job.request_hash and request_hash != job.request_hash:
                raise IdempotencyConflict(
                    "idempotency key was reused with a different request"
                )
            return self._job_snapshot(job)

    def list_jobs(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        query: str | None = None,
        needs_action: bool | None = None,
        approval_mode: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            statement = select(Job).where(Job.tenant_id == tenant_id, Job.deleted_at.is_(None))
            if status:
                statement = statement.where(Job.status == status)
            if approval_mode:
                statement = statement.where(Job.approval_mode == approval_mode)
            if query:
                escaped = query.replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(
                    or_(Job.project_name.ilike(f"%{escaped}%", escape="\\"), Job.id.ilike(f"%{escaped}%", escape="\\"))
                )
            if created_from:
                statement = statement.where(Job.created_at >= created_from)
            if created_to:
                statement = statement.where(Job.created_at <= created_to)
            statement = statement.order_by(Job.updated_at.desc(), Job.id.desc()).limit(limit).offset(offset)
            jobs = list(session.scalars(statement))
            snapshots = [self._job_snapshot(job) for job in jobs]
            if needs_action is not None:
                snapshots = [item for item in snapshots if bool(item.get("needs_action")) == needs_action]
            return snapshots

    def count_jobs(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        query: str | None = None,
        needs_action: bool | None = None,
        approval_mode: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int:
        with self.database.session() as session:
            statement = select(Job).where(Job.tenant_id == tenant_id, Job.deleted_at.is_(None))
            if status:
                statement = statement.where(Job.status == status)
            if approval_mode:
                statement = statement.where(Job.approval_mode == approval_mode)
            if query:
                escaped = query.replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(
                    or_(
                        Job.project_name.ilike(f"%{escaped}%", escape="\\"),
                        Job.id.ilike(f"%{escaped}%", escape="\\"),
                    )
                )
            if created_from:
                statement = statement.where(Job.created_at >= created_from)
            if created_to:
                statement = statement.where(Job.created_at <= created_to)
            if needs_action is None:
                return int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
            jobs = session.scalars(statement)
            return sum(
                1
                for job in jobs
                if bool(job.manifest.get("needs_action")) == needs_action
            )

    def list_lifecycle_jobs(
        self,
        tenant_id: str,
        *,
        state: str = "deleted",
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        if state not in {"active", "deleted", "all"}:
            raise RepositoryError(f"unsupported lifecycle state: {state}")
        with self.database.session() as session:
            self._require_tenant(session, tenant_id)
            statement = select(Job).where(Job.tenant_id == tenant_id)
            if state == "active":
                statement = statement.where(Job.deleted_at.is_(None))
            elif state == "deleted":
                statement = statement.where(Job.deleted_at.is_not(None))
            if query:
                escaped = query.replace("%", "\\%").replace("_", "\\_")
                statement = statement.where(
                    or_(
                        Job.project_name.ilike(f"%{escaped}%", escape="\\"),
                        Job.id.ilike(f"%{escaped}%", escape="\\"),
                    )
                )
            total = int(
                session.scalar(select(func.count()).select_from(statement.subquery())) or 0
            )
            rows = session.scalars(
                statement.order_by(
                    Job.deleted_at.is_(None),
                    Job.deleted_at.desc(),
                    Job.updated_at.desc(),
                    Job.id.desc(),
                )
                .limit(max(1, min(limit, 200)))
                .offset(max(0, offset))
            )
            return [self._job_snapshot(row) for row in rows], total

    def replace_manifest(
        self,
        tenant_id: str,
        job_id: str,
        manifest: dict[str, Any],
        *,
        expected_version: int | None = None,
        outbox_topic: str | None = None,
    ) -> dict[str, Any]:
        manifest_copy = copy.deepcopy(manifest)
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=True, for_update=True)
            if expected_version is not None and job.row_version != expected_version:
                raise RepositoryConflict(
                    f"job version changed: expected {expected_version}, current {job.row_version}"
                )
            job.manifest = manifest_copy
            job.manifest_sha256 = sha256_json(manifest_copy)
            job.project_name = manifest_copy["project_name"]
            job.status = manifest_copy["status"]
            job.stage = manifest_copy["stage"]
            job.input_mode = manifest_copy.get("input_mode", job.input_mode)
            job.approval_mode = manifest_copy.get("approval_mode", job.approval_mode)
            job.row_version += 1
            job.updated_at = utc_now()
            if outbox_topic:
                self._add_outbox(
                    session,
                    tenant_id,
                    outbox_topic,
                    "job",
                    job_id,
                    {"tenant_id": tenant_id, "job_id": job_id, "row_version": job.row_version},
                )
            session.flush()
            return self._job_snapshot(job)

    def append_event(
        self,
        tenant_id: str,
        job_id: str,
        event_type: str,
        *,
        stage: str | None,
        message: str,
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            job.event_sequence += 1
            event = JobEvent(
                tenant_id=tenant_id,
                job_id=job_id,
                sequence=job.event_sequence,
                event_type=event_type,
                stage=stage,
                message=message,
                payload=copy.deepcopy(payload or {}),
                occurred_at=occurred_at or utc_now(),
            )
            session.add(event)
            self._add_outbox(
                session,
                tenant_id,
                "job.event",
                "job",
                job_id,
                {
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "sequence": job.event_sequence,
                    "event_type": event_type,
                },
            )
            session.flush()
            return self._event_dict(event)

    def list_events(self, tenant_id: str, job_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id)
            events = session.scalars(
                select(JobEvent)
                .where(
                    JobEvent.tenant_id == tenant_id,
                    JobEvent.job_id == job_id,
                    JobEvent.sequence > after,
                )
                .order_by(JobEvent.sequence)
            )
            return [self._event_dict(event) for event in events]

    # -- Stage runs, leases, outbox, and recovery ----------------------------

    def list_stage_runs(self, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id, include_deleted=True)
            runs = session.scalars(
                select(JobStageRun)
                .where(JobStageRun.tenant_id == tenant_id, JobStageRun.job_id == job_id)
                .order_by(JobStageRun.created_at, JobStageRun.attempt)
            )
            return [self._stage_dict(run) for run in runs]

    def request_job_cancel(
        self,
        tenant_id: str,
        job_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Request an idempotent cancellation and fence all future commits."""

        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            if job.status == "canceled":
                return {**self._job_snapshot(job), "cancellation": "already_canceled"}
            if job.status in {"succeeded", "failed"}:
                return {**self._job_snapshot(job), "cancellation": "job_terminal"}

            queued = list(
                session.scalars(
                    select(JobStageRun)
                    .where(
                        JobStageRun.tenant_id == tenant_id,
                        JobStageRun.job_id == job_id,
                        JobStageRun.status == "queued",
                    )
                    .with_for_update()
                )
            )
            for run in queued:
                run.status = "canceled"
                run.error_code = "canceled"
                run.error_message = reason or "canceled by user"
                run.retryable = False
                run.finished_at = current

            leases = list(
                session.scalars(
                    select(WorkerLease)
                    .where(WorkerLease.tenant_id == tenant_id, WorkerLease.job_id == job_id)
                    .with_for_update()
                )
            )
            for lease in leases:
                lease.cancel_requested = True

            manifest = copy.deepcopy(job.manifest)
            manifest.update(
                {
                    "status": "canceling" if leases else "canceled",
                    "display_status": "正在取消" if leases else "已取消",
                    "cancel_requested": True,
                    "can_cancel": False,
                    "can_retry": not leases,
                    "needs_action": False,
                    "next_action": "等待运行中的进程退出" if leases else "可显式恢复任务",
                }
            )
            self._apply_manifest(job, manifest)
            self._record_job_event(
                session,
                job,
                event_type="job.cancel_requested" if leases else "job.canceled",
                stage=job.stage,
                message="已请求取消任务" if leases else "任务已取消",
                payload={
                    "queued_stages_canceled": len(queued),
                    "running_stages_signaled": len(leases),
                    "reason": reason,
                },
                occurred_at=current,
            )
            if not leases:
                self._release_job_capacity(session, tenant_id, job_id, "canceled", current)
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    id=new_id("aud"),
                    actor_id=actor_id,
                    action="job.cancel",
                    resource_type="job",
                    resource_id=job_id,
                    result="succeeded",
                    request_id=request_id,
                    payload={"reason": reason, "running_stages_signaled": len(leases)},
                    occurred_at=current,
                )
            )
            session.flush()
            return {
                **self._job_snapshot(job),
                "cancellation": "requested" if leases else "canceled",
            }

    def retry_job(
        self,
        tenant_id: str,
        job_id: str,
        *,
        actor_id: str,
        stage: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Recover a terminal job by creating a new immutable stage attempt."""

        current = as_utc(now or utc_now())
        with _tenant_quota_lock(tenant_id):
            with self.database.transaction() as session:
                tenant = self._require_tenant(session, tenant_id, for_update=True)
                job = self._require_job(session, tenant_id, job_id, for_update=True)

                active = session.scalar(
                    select(JobStageRun)
                    .where(
                        JobStageRun.tenant_id == tenant_id,
                        JobStageRun.job_id == job_id,
                        JobStageRun.status.in_(("queued", "running")),
                    )
                    .order_by(JobStageRun.created_at.desc())
                    .limit(1)
                )
                if job.status in {"queued", "running", "canceling"} and active is not None:
                    return self._job_snapshot(job), self._stage_dict(active), False
                if job.status not in {"failed", "canceled"}:
                    raise RepositoryConflict("only failed or canceled jobs can be retried")

                statement = select(JobStageRun).where(
                    JobStageRun.tenant_id == tenant_id,
                    JobStageRun.job_id == job_id,
                    JobStageRun.status.in_(("dead_letter", "failed", "lease_expired", "canceled")),
                )
                if stage:
                    statement = statement.where(JobStageRun.stage == stage)
                source = session.scalar(
                    statement.order_by(JobStageRun.created_at.desc(), JobStageRun.attempt.desc()).limit(1)
                )
                if source is None:
                    raise RepositoryNotFound("no recoverable stage run found")

                self._activate_job_capacity(session, tenant, job_id, current)
                latest_attempt = int(
                    session.scalar(
                        select(func.max(JobStageRun.attempt)).where(
                            JobStageRun.tenant_id == tenant_id,
                            JobStageRun.job_id == job_id,
                            JobStageRun.stage == source.stage,
                        )
                    )
                    or 0
                )
                latest_cycle = int(
                    session.scalar(
                        select(func.max(JobStageRun.retry_cycle)).where(
                            JobStageRun.tenant_id == tenant_id,
                            JobStageRun.job_id == job_id,
                            JobStageRun.stage == source.stage,
                        )
                    )
                    or 0
                )
                manifest = copy.deepcopy(job.manifest)
                manifest.update(
                    {
                        "status": "queued",
                        "display_status": "已恢复，等待执行",
                        "stage": source.stage,
                        "needs_action": False,
                        "next_action": None,
                        "can_retry": False,
                        "can_cancel": True,
                        "cancel_requested": False,
                        "error": None,
                    }
                )
                self._apply_manifest(job, manifest)
                run = JobStageRun(
                    tenant_id=tenant_id,
                    id=new_id("run"),
                    job_id=job_id,
                    stage=source.stage,
                    queue_name=source.queue_name,
                    attempt=latest_attempt + 1,
                    retry_cycle=latest_cycle + 1,
                    cycle_attempt=1,
                    input_hash=source.input_hash,
                    route_snapshot_hash=source.route_snapshot_hash,
                    config_snapshot_hash=source.config_snapshot_hash,
                    expected_job_version=job.row_version,
                    status="queued",
                    priority="interactive",
                    created_at=current,
                )
                session.add(run)
                self._enqueue_stage_outbox(session, run)
                self._record_job_event(
                    session,
                    job,
                    event_type="job.retried",
                    stage=run.stage,
                    message="任务已从最近可恢复阶段重新入队",
                    payload={
                        "source_stage_run_id": source.id,
                        "stage_run_id": run.id,
                        "retry_cycle": run.retry_cycle,
                    },
                    occurred_at=current,
                )
                session.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        id=new_id("aud"),
                        actor_id=actor_id,
                        action="job.retry",
                        resource_type="job",
                        resource_id=job_id,
                        result="succeeded",
                        request_id=request_id,
                        payload={"stage": run.stage, "retry_cycle": run.retry_cycle},
                        occurred_at=current,
                    )
                )
                session.flush()
                return self._job_snapshot(job), self._stage_dict(run), True

    def create_stage_run(
        self,
        identity: StageIdentity,
        *,
        queue_name: str,
        priority: str = "normal",
        expected_job_version: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self.database.transaction() as session:
            job = self._require_job(session, identity.tenant_id, identity.job_id, for_update=True)
            successful = self._find_successful_stage(session, identity)
            if successful is not None:
                return self._stage_dict(successful), True
            active = self._find_active_stage(session, identity)
            if active is not None:
                return self._stage_dict(active), True
            latest_attempt = session.scalar(
                select(func.max(JobStageRun.attempt)).where(
                    JobStageRun.tenant_id == identity.tenant_id,
                    JobStageRun.job_id == identity.job_id,
                    JobStageRun.stage == identity.stage,
                )
            )
            run = JobStageRun(
                tenant_id=identity.tenant_id,
                id=new_id("run"),
                job_id=identity.job_id,
                stage=identity.stage,
                queue_name=queue_name,
                attempt=int(latest_attempt or 0) + 1,
                retry_cycle=0,
                cycle_attempt=1,
                input_hash=identity.input_hash,
                route_snapshot_hash=identity.route_snapshot_hash,
                config_snapshot_hash=identity.config_snapshot_hash,
                expected_job_version=expected_job_version or job.row_version,
                status="queued",
                priority=priority,
            )
            session.add(run)
            self._enqueue_stage_outbox(session, run)
            session.flush()
            return self._stage_dict(run), False

    def enqueue_revision_request(
        self,
        tenant_id: str,
        job_id: str,
        *,
        domain: str,
        manifest_key: str,
        base_revision: str,
        request_record: dict[str, Any],
        request_hash: str,
        stage: str,
        queue_name: str,
        route_snapshot_hash: str,
        config_snapshot_hash: str,
        expected_job_version: int,
        actor_id: str,
        request_id: str | None = None,
        priority: str = "interactive",
    ) -> dict[str, Any]:
        """Persist model revision feedback and enqueue its stage atomically.

        Queue messages intentionally contain identifiers and immutable hashes
        only. Workers load the feedback from the authoritative job manifest.
        """

        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            if job.row_version != expected_job_version:
                raise RepositoryConflict(
                    f"job version changed: expected {expected_job_version}, current {job.row_version}"
                )
            revision = session.get(ArtifactRevision, (tenant_id, base_revision))
            if (
                revision is None
                or revision.job_id != job_id
                or revision.domain != domain
                or not revision.is_current
                or job.manifest.get("current_revisions", {}).get(manifest_key) != base_revision
            ):
                raise RepositoryConflict("the requested base revision is no longer current")

            identity = StageIdentity(
                tenant_id=tenant_id,
                job_id=job_id,
                stage=stage,
                input_hash=request_hash,
                route_snapshot_hash=route_snapshot_hash,
                config_snapshot_hash=config_snapshot_hash,
            )
            existing = self._find_successful_stage(session, identity)
            if existing is None:
                existing = self._find_active_stage(session, identity)
            if existing is not None:
                matching = next(
                    (
                        copy.deepcopy(item)
                        for item in job.manifest.get("model_revision_requests", {}).values()
                        if item.get("request_hash") == request_hash
                    ),
                    copy.deepcopy(request_record),
                )
                matching.setdefault("status", existing.status)
                matching.setdefault("stage_run_id", existing.id)
                matching.setdefault("updated_at", (existing.finished_at or existing.started_at or existing.created_at).isoformat())
                return {
                    "job": self._job_snapshot(job),
                    "stage_run": self._stage_dict(existing),
                    "revision_request": matching,
                    "reused": True,
                }

            current = utc_now()
            run_id = new_id("run")
            persisted_request = copy.deepcopy(request_record)
            persisted_request.update(
                {
                    "status": "queued",
                    "stage_run_id": run_id,
                    "updated_at": current.isoformat(),
                }
            )
            manifest = copy.deepcopy(job.manifest)
            manifest.setdefault("model_revision_requests", {})[str(request_record["request_id"])] = persisted_request
            manifest.update(
                {
                    "status": "queued",
                    "display_status": "模型修订请求已入队",
                    "stage": stage,
                    "needs_action": False,
                    "can_approve": False,
                    "next_action": None,
                    "updated_at": current.isoformat(),
                }
            )
            self._apply_manifest(job, manifest)
            latest_attempt = session.scalar(
                select(func.max(JobStageRun.attempt)).where(
                    JobStageRun.tenant_id == tenant_id,
                    JobStageRun.job_id == job_id,
                    JobStageRun.stage == stage,
                )
            )
            run = JobStageRun(
                tenant_id=tenant_id,
                id=run_id,
                job_id=job_id,
                stage=stage,
                queue_name=queue_name,
                attempt=int(latest_attempt or 0) + 1,
                retry_cycle=0,
                cycle_attempt=1,
                input_hash=request_hash,
                route_snapshot_hash=route_snapshot_hash,
                config_snapshot_hash=config_snapshot_hash,
                expected_job_version=job.row_version,
                status="queued",
                priority=priority,
                created_at=current,
            )
            session.add(run)
            self._enqueue_stage_outbox(session, run)
            self._record_job_event(
                session,
                job,
                event_type=f"revision.{domain}.model_requested",
                stage=stage,
                message=f"已提交 {domain} 模型修订请求",
                payload={
                    "revision": base_revision,
                    "revision_request_id": request_record["request_id"],
                    "stage_run_id": run.id,
                },
            )
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    id=new_id("aud"),
                    actor_id=actor_id,
                    action="revision.model_request",
                    resource_type="artifact_revision",
                    resource_id=base_revision,
                    result="succeeded",
                    request_id=request_id,
                    payload={
                        "job_id": job_id,
                        "domain": domain,
                        "stage": stage,
                        "revision_request_id": request_record["request_id"],
                    },
                )
            )
            session.flush()
            return {
                "job": self._job_snapshot(job),
                "stage_run": self._stage_dict(run),
                "revision_request": copy.deepcopy(persisted_request),
                "reused": False,
            }

    def get_stage_run(self, tenant_id: str, stage_run_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            run = self._require_stage_run(session, tenant_id, stage_run_id)
            return self._stage_dict(run)

    def claim_stage_run(
        self,
        tenant_id: str,
        stage_run_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.transaction() as session:
            run = self._require_stage_run(session, tenant_id, stage_run_id, for_update=True)
            job = self._require_job(session, tenant_id, run.job_id, for_update=True)
            if run.status == "succeeded":
                return {**self._stage_dict(run), "claim": "already_succeeded"}
            if run.status != "queued":
                raise LeaseConflict(f"stage run is not queued: {run.status}")
            identity = self._identity_from_run(run)
            prior = self._find_successful_stage(session, identity, exclude_id=run.id)
            if prior is not None:
                run.status = "superseded"
                run.superseded = True
                run.finished_at = current
                return {**self._stage_dict(run), "claim": "duplicate_success"}
            competing = self._find_active_stage(
                session,
                identity,
                exclude_id=run.id,
                statuses=("running",),
            )
            if competing is not None:
                run.status = "superseded"
                run.superseded = True
                run.finished_at = current
                return {**self._stage_dict(run), "claim": "duplicate_running"}
            if job.row_version != run.expected_job_version:
                run.status = "superseded"
                run.superseded = True
                run.finished_at = current
                return {**self._stage_dict(run), "claim": "stale_job_version"}
            if job.status in TERMINAL_JOB_STATUSES or job.deleted_at is not None:
                run.status = "canceled"
                run.finished_at = current
                return {**self._stage_dict(run), "claim": "job_terminal"}
            expiry = current + timedelta(seconds=lease_seconds)
            run.status = "running"
            run.worker_id = worker_id
            run.started_at = run.started_at or current
            run.heartbeat_at = current
            run.lease_expires_at = expiry
            session.add(
                WorkerLease(
                    tenant_id=tenant_id,
                    stage_run_id=run.id,
                    job_id=run.job_id,
                    worker_id=worker_id,
                    heartbeat_at=current,
                    lease_expires_at=expiry,
                )
            )
            session.flush()
            return {**self._stage_dict(run), "claim": "claimed"}

    def heartbeat_stage_run(
        self,
        tenant_id: str,
        stage_run_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.transaction() as session:
            run = self._require_stage_run(session, tenant_id, stage_run_id, for_update=True)
            lease = session.get(WorkerLease, (tenant_id, stage_run_id))
            if run.status != "running" or lease is None or lease.worker_id != worker_id:
                raise LeaseConflict("worker does not own this running stage")
            expiry = current + timedelta(seconds=lease_seconds)
            run.heartbeat_at = current
            run.lease_expires_at = expiry
            lease.heartbeat_at = current
            lease.lease_expires_at = expiry
            return {**self._stage_dict(run), "cancel_requested": lease.cancel_requested}

    def complete_stage_run(
        self,
        tenant_id: str,
        stage_run_id: str,
        *,
        worker_id: str,
        output_hash: str,
        manifest: dict[str, Any] | None = None,
        paid_result_key: str | None = None,
        next_stage: str | None = None,
        next_queue_name: str | None = None,
        next_input_hash: str | None = None,
        next_route_snapshot_hash: str | None = None,
        next_config_snapshot_hash: str | None = None,
        next_priority: str | None = None,
        artifact_bundles: Sequence[ArtifactBundleRegistration] = (),
        model_runs: Sequence[ModelRunRegistration] = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.transaction() as session:
            run = self._require_stage_run(session, tenant_id, stage_run_id, for_update=True)
            job = self._require_job(session, tenant_id, run.job_id, for_update=True)
            lease = self._require_owned_lease(session, run, worker_id, current)
            if lease.cancel_requested or job.status in {"canceling", "canceled"}:
                run.status = "canceled"
                run.error_code = "canceled"
                run.error_message = "result discarded after cancellation was requested"
                run.retryable = False
                run.output_hash = output_hash
                run.paid_result_key = paid_result_key
                run.finished_at = current
                run.lease_expires_at = None
                session.delete(lease)
                self._finalize_job_cancellation(session, job, current)
                session.flush()
                return {**self._stage_dict(run), "commit": "canceled"}
            prior = self._find_successful_stage(session, self._identity_from_run(run), exclude_id=run.id)
            if prior is not None:
                run.status = "superseded"
                run.superseded = True
                run.output_hash = output_hash
                run.paid_result_key = paid_result_key
                run.finished_at = current
                session.delete(session.get(WorkerLease, (tenant_id, stage_run_id)))
                return {**self._stage_dict(run), "commit": "duplicate_success"}
            if job.row_version != run.expected_job_version:
                run.status = "superseded"
                run.superseded = True
                run.output_hash = output_hash
                run.paid_result_key = paid_result_key
                run.finished_at = current
                session.delete(session.get(WorkerLease, (tenant_id, stage_run_id)))
                return {**self._stage_dict(run), "commit": "stale_job_version"}
            registered_revisions = [
                self._register_stage_artifact_bundle(session, job, run, bundle)
                for bundle in artifact_bundles
            ]
            registered_model_runs = [
                self._register_model_run(session, job, registration, stage_run_id=run.id)
                for registration in model_runs
            ]
            run.status = "succeeded"
            run.output_hash = output_hash
            run.paid_result_key = paid_result_key
            run.finished_at = current
            run.lease_expires_at = None
            if manifest is not None:
                self._apply_manifest(job, manifest)
                if job.status in TERMINAL_JOB_STATUSES:
                    self._release_job_capacity(session, tenant_id, job.id, job.status, current)
            session.delete(session.get(WorkerLease, (tenant_id, stage_run_id)))
            self._add_outbox(
                session,
                tenant_id,
                "stage.succeeded",
                "stage_run",
                run.id,
                {"tenant_id": tenant_id, "job_id": run.job_id, "stage_run_id": run.id},
            )
            next_run: JobStageRun | None = None
            next_reused = False
            if next_stage is not None and job.status not in TERMINAL_JOB_STATUSES:
                if not next_queue_name:
                    raise RepositoryError("next_queue_name is required when next_stage is provided")
                identity = StageIdentity(
                    tenant_id=tenant_id,
                    job_id=run.job_id,
                    stage=next_stage,
                    input_hash=next_input_hash or output_hash,
                    route_snapshot_hash=next_route_snapshot_hash or run.route_snapshot_hash,
                    config_snapshot_hash=next_config_snapshot_hash or run.config_snapshot_hash,
                )
                next_run = self._find_successful_stage(session, identity)
                if next_run is None:
                    next_run = self._find_active_stage(session, identity)
                if next_run is not None:
                    next_reused = True
                else:
                    latest_attempt = session.scalar(
                        select(func.max(JobStageRun.attempt)).where(
                            JobStageRun.tenant_id == tenant_id,
                            JobStageRun.job_id == run.job_id,
                            JobStageRun.stage == next_stage,
                        )
                    )
                    next_run = JobStageRun(
                        tenant_id=tenant_id,
                        id=new_id("run"),
                        job_id=run.job_id,
                        stage=next_stage,
                        queue_name=next_queue_name,
                        attempt=int(latest_attempt or 0) + 1,
                        retry_cycle=0,
                        cycle_attempt=1,
                        input_hash=identity.input_hash,
                        route_snapshot_hash=identity.route_snapshot_hash,
                        config_snapshot_hash=identity.config_snapshot_hash,
                        expected_job_version=job.row_version,
                        status="queued",
                        priority=next_priority or run.priority,
                        created_at=current,
                    )
                    session.add(next_run)
                    self._enqueue_stage_outbox(session, next_run)
                    self._record_job_event(
                        session,
                        job,
                        event_type="stage.queued",
                        stage=next_stage,
                        message=f"阶段 {next_stage} 已入队",
                        payload={
                            "previous_stage_run_id": run.id,
                            "stage_run_id": next_run.id,
                            "queue_name": next_queue_name,
                        },
                        occurred_at=current,
                    )
            session.flush()
            result = {**self._stage_dict(run), "commit": "succeeded"}
            if registered_revisions:
                result["artifact_revision_ids"] = [revision.id for revision in registered_revisions]
            if registered_model_runs:
                result["model_run_ids"] = [model_run.id for model_run in registered_model_runs]
            if next_run is not None:
                result.update(
                    {
                        "next_stage_run_id": next_run.id,
                        "next_stage": next_run.stage,
                        "next_stage_reused": next_reused,
                    }
                )
            return result

    def _register_stage_artifact_bundle(
        self,
        session: Session,
        job: Job,
        run: JobStageRun,
        bundle: ArtifactBundleRegistration,
    ) -> ArtifactRevision:
        if not bundle.blobs:
            raise RepositoryError("artifact bundle must contain at least one blob")
        logical_names = [item.logical_name for item in bundle.blobs]
        if len(logical_names) != len(set(logical_names)):
            raise RepositoryConflict("artifact bundle logical names must be unique")
        existing = session.get(ArtifactRevision, (job.tenant_id, bundle.revision_id))
        if existing is not None:
            if (
                existing.job_id != job.id
                or existing.domain != bundle.domain
                or existing.revision_hash != bundle.revision_hash
            ):
                raise RepositoryConflict("artifact revision ID already exists with different content")
            revision = existing
        else:
            revision = session.scalar(
                select(ArtifactRevision).where(
                    ArtifactRevision.tenant_id == job.tenant_id,
                    ArtifactRevision.job_id == job.id,
                    ArtifactRevision.domain == bundle.domain,
                    ArtifactRevision.revision_hash == bundle.revision_hash,
                )
            )
        if revision is None:
            object_manifest = [
                {
                    "logical_name": item.logical_name,
                    "object_key": item.object_key,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "media_type": item.media_type,
                }
                for item in sorted(bundle.blobs, key=lambda item: item.logical_name)
            ]
            revision = ArtifactRevision(
                tenant_id=job.tenant_id,
                id=bundle.revision_id,
                job_id=job.id,
                domain=bundle.domain,
                parent_id=bundle.parent_id,
                stage_run_id=run.id,
                revision_hash=bundle.revision_hash,
                object_manifest=object_manifest,
                created_by=bundle.created_by,
                is_current=False,
            )
            session.add(revision)
            session.flush()
            for item in bundle.blobs:
                session.add(
                    ArtifactBlob(
                        tenant_id=job.tenant_id,
                        id=new_id("blob"),
                        job_id=job.id,
                        revision_id=revision.id,
                        logical_name=item.logical_name,
                        object_key=item.object_key,
                        size_bytes=item.size_bytes,
                        sha256=item.sha256,
                        media_type=item.media_type,
                        created_stage=run.stage,
                        scan_status=item.scan_status,
                        encryption=copy.deepcopy(item.encryption or {}),
                        pending=False,
                    )
                )
            self._add_outbox(
                session,
                job.tenant_id,
                "artifact.revision.committed",
                "artifact_revision",
                revision.id,
                {
                    "tenant_id": job.tenant_id,
                    "job_id": job.id,
                    "revision_id": revision.id,
                    "domain": revision.domain,
                    "revision_hash": revision.revision_hash,
                    "artifact_count": len(bundle.blobs),
                    "stage_run_id": run.id,
                },
            )
        if bundle.make_current and not revision.is_current:
            session.execute(
                update(ArtifactRevision)
                .where(
                    ArtifactRevision.tenant_id == job.tenant_id,
                    ArtifactRevision.job_id == job.id,
                    ArtifactRevision.domain == bundle.domain,
                    ArtifactRevision.is_current.is_(True),
                    ArtifactRevision.id != revision.id,
                )
                .values(is_current=False)
            )
            revision.is_current = True
        return revision

    def fail_stage_run(
        self,
        tenant_id: str,
        stage_run_id: str,
        *,
        worker_id: str | None,
        error_code: str,
        error_message: str,
        retryable: bool,
        max_attempts: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.transaction() as session:
            run = self._require_stage_run(session, tenant_id, stage_run_id, for_update=True)
            job = self._require_job(session, tenant_id, run.job_id, for_update=True)
            owned_lease: WorkerLease | None = None
            if worker_id is not None:
                owned_lease = self._require_owned_lease(
                    session, run, worker_id, current, allow_expired=True
                )
            lease = session.get(WorkerLease, (tenant_id, stage_run_id))
            if lease is not None:
                session.delete(lease)
            if (
                (owned_lease is not None and owned_lease.cancel_requested)
                or job.status in {"canceling", "canceled"}
            ):
                run.status = "canceled"
                run.error_code = "canceled"
                run.error_message = "stage stopped after cancellation was requested"
                run.retryable = False
                run.finished_at = current
                run.lease_expires_at = None
                self._finalize_job_cancellation(session, job, current)
                session.flush()
                return {**self._stage_dict(run), "canceled": True}
            run.error_code = error_code
            run.error_message = error_message[:4000]
            run.retryable = retryable
            run.finished_at = current
            run.lease_expires_at = None
            if retryable and run.cycle_attempt < max_attempts:
                run.status = "failed"
                retry = JobStageRun(
                    tenant_id=tenant_id,
                    id=new_id("run"),
                    job_id=run.job_id,
                    stage=run.stage,
                    queue_name=run.queue_name,
                    attempt=run.attempt + 1,
                    retry_cycle=run.retry_cycle,
                    cycle_attempt=run.cycle_attempt + 1,
                    input_hash=run.input_hash,
                    route_snapshot_hash=run.route_snapshot_hash,
                    config_snapshot_hash=run.config_snapshot_hash,
                    expected_job_version=job.row_version,
                    status="queued",
                    priority=run.priority,
                )
                session.add(retry)
                self._enqueue_stage_outbox(session, retry)
                result = {**self._stage_dict(run), "requeued_stage_run_id": retry.id}
            else:
                run.status = "dead_letter"
                manifest = copy.deepcopy(job.manifest)
                manifest.update(
                    {
                        "status": "failed",
                        "display_status": "需要运维处理",
                        "stage": run.stage,
                        "needs_action": True,
                        "next_action": "查看 dead letter 并由管理员恢复",
                        "can_retry": True,
                        "can_cancel": False,
                        "error": {
                            "error_id": new_id("err"),
                            "stage": run.stage,
                            "code": error_code,
                            "message": error_message[:1000],
                        },
                    }
                )
                self._apply_manifest(job, manifest)
                self._release_job_capacity(session, tenant_id, job.id, "failed", current)
                self._add_outbox(
                    session,
                    tenant_id,
                    f"queue.{run.queue_name}.dead_letter",
                    "stage_run",
                    run.id,
                    {
                        "tenant_id": tenant_id,
                        "job_id": run.job_id,
                        "stage_run_id": run.id,
                        "attempt": run.attempt,
                        "error_code": error_code,
                    },
                )
                result = {**self._stage_dict(run), "dead_letter": True}
            session.flush()
            return result

    def expire_running_leases_for_recovery(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        """Expire every authoritative running lease before queue reconstruction.

        Redis is deliberately not authoritative. After a database restore, any
        worker represented by the restored lease table is gone, so retaining
        the old lease deadline would unnecessarily stall recovery.
        """

        current = as_utc(now or utc_now())
        expired_at = current - timedelta(microseconds=1)
        expired = 0
        with self.database.transaction() as session:
            leases = list(
                session.scalars(
                    select(WorkerLease)
                    .join(
                        JobStageRun,
                        and_(
                            JobStageRun.tenant_id == WorkerLease.tenant_id,
                            JobStageRun.id == WorkerLease.stage_run_id,
                        ),
                    )
                    .where(JobStageRun.status == "running")
                    .with_for_update()
                )
            )
            for lease in leases:
                run = self._require_stage_run(
                    session,
                    lease.tenant_id,
                    lease.stage_run_id,
                    for_update=True,
                )
                lease.lease_expires_at = expired_at
                run.lease_expires_at = expired_at
                expired += 1
        return expired

    def reap_expired_leases(
        self,
        *,
        now: datetime | None = None,
        max_attempts: int,
    ) -> list[dict[str, Any]]:
        current = now or utc_now()
        recovered: list[dict[str, Any]] = []
        with self.database.transaction() as session:
            leases = list(
                session.scalars(
                    select(WorkerLease)
                    .where(WorkerLease.lease_expires_at < current)
                    .order_by(WorkerLease.lease_expires_at)
                    .with_for_update()
                )
            )
            for lease in leases:
                run = self._require_stage_run(session, lease.tenant_id, lease.stage_run_id, for_update=True)
                if run.status != "running":
                    session.delete(lease)
                    continue
                job = self._require_job(session, lease.tenant_id, run.job_id, for_update=True)
                if lease.cancel_requested or job.status in {"canceling", "canceled"}:
                    run.status = "canceled"
                    run.error_code = "canceled"
                    run.error_message = "worker lease expired after cancellation was requested"
                    run.retryable = False
                    run.finished_at = current
                    session.delete(lease)
                    self._finalize_job_cancellation(session, job, current)
                    recovered.append(
                        {
                            "canceled_stage_run_id": run.id,
                            "tenant_id": run.tenant_id,
                            "job_id": run.job_id,
                        }
                    )
                    continue
                run.status = "lease_expired"
                run.error_code = "worker_lease_expired"
                run.error_message = "worker heartbeat stopped before the lease deadline"
                run.finished_at = current
                session.delete(lease)
                if run.cycle_attempt < max_attempts:
                    retry = JobStageRun(
                        tenant_id=run.tenant_id,
                        id=new_id("run"),
                        job_id=run.job_id,
                        stage=run.stage,
                        queue_name=run.queue_name,
                        attempt=run.attempt + 1,
                        retry_cycle=run.retry_cycle,
                        cycle_attempt=run.cycle_attempt + 1,
                        input_hash=run.input_hash,
                        route_snapshot_hash=run.route_snapshot_hash,
                        config_snapshot_hash=run.config_snapshot_hash,
                        expected_job_version=job.row_version,
                        status="queued",
                        priority=run.priority,
                    )
                    session.add(retry)
                    self._enqueue_stage_outbox(session, retry)
                    recovered.append(
                        {
                            "expired_stage_run_id": run.id,
                            "requeued_stage_run_id": retry.id,
                            "tenant_id": run.tenant_id,
                            "job_id": run.job_id,
                        }
                    )
                else:
                    run.status = "dead_letter"
                    manifest = copy.deepcopy(job.manifest)
                    manifest.update(
                        {
                            "status": "failed",
                            "display_status": "需要运维处理",
                            "stage": run.stage,
                            "needs_action": True,
                            "next_action": "查看 dead letter 并由管理员恢复",
                            "can_retry": True,
                            "can_cancel": False,
                            "error": {
                                "error_id": new_id("err"),
                                "stage": run.stage,
                                "code": "worker_lease_expired",
                                "message": run.error_message,
                            },
                        }
                    )
                    self._apply_manifest(job, manifest)
                    self._release_job_capacity(
                        session, run.tenant_id, run.job_id, "failed", current
                    )
                    self._add_outbox(
                        session,
                        run.tenant_id,
                        f"queue.{run.queue_name}.dead_letter",
                        "stage_run",
                        run.id,
                        {
                            "tenant_id": run.tenant_id,
                            "job_id": run.job_id,
                            "stage_run_id": run.id,
                            "attempt": run.attempt,
                            "error_code": "worker_lease_expired",
                        },
                    )
                    recovered.append(
                        {
                            "dead_letter_stage_run_id": run.id,
                            "tenant_id": run.tenant_id,
                            "job_id": run.job_id,
                        }
                    )
        return recovered

    def pending_outbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.session() as session:
            events = session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.delivered_at.is_(None))
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(limit)
            )
            return [self._outbox_dict(event) for event in events]

    def operations_snapshot(
        self,
        tenant_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a tenant-safe, low-cardinality operations overview."""

        current = as_utc(now or utc_now())
        with self.database.session() as session:
            self._require_tenant(session, tenant_id)
            jobs_by_status = {
                str(status): int(count)
                for status, count in session.execute(
                    select(Job.status, func.count())
                    .where(Job.tenant_id == tenant_id)
                    .group_by(Job.status)
                )
            }
            stage_counts = {
                (str(queue_name), str(stage_status)): int(count)
                for queue_name, stage_status, count in session.execute(
                    select(JobStageRun.queue_name, JobStageRun.status, func.count())
                    .where(JobStageRun.tenant_id == tenant_id)
                    .group_by(JobStageRun.queue_name, JobStageRun.status)
                )
            }
            oldest_queued = {
                str(queue_name): as_utc(created_at)
                for queue_name, created_at in session.execute(
                    select(JobStageRun.queue_name, func.min(JobStageRun.created_at))
                    .where(
                        JobStageRun.tenant_id == tenant_id,
                        JobStageRun.status == "queued",
                    )
                    .group_by(JobStageRun.queue_name)
                )
                if created_at is not None
            }
            queues = []
            for queue_name in ("planning", "media", "render", "qa"):
                statuses = {
                    status: count
                    for (candidate, status), count in stage_counts.items()
                    if candidate == queue_name
                }
                oldest = oldest_queued.get(queue_name)
                queues.append(
                    {
                        "queue": queue_name,
                        "by_status": statuses,
                        "queued": statuses.get("queued", 0),
                        "running": statuses.get("running", 0),
                        "dead_letter": statuses.get("dead_letter", 0),
                        "oldest_queued_age_seconds": (
                            max(0, int((current - oldest).total_seconds()))
                            if oldest is not None
                            else None
                        ),
                    }
                )

            active_leases = int(
                session.scalar(
                    select(func.count()).select_from(WorkerLease).where(
                        WorkerLease.tenant_id == tenant_id,
                        WorkerLease.lease_expires_at >= current,
                    )
                )
                or 0
            )
            expired_leases = int(
                session.scalar(
                    select(func.count()).select_from(WorkerLease).where(
                        WorkerLease.tenant_id == tenant_id,
                        WorkerLease.lease_expires_at < current,
                    )
                )
                or 0
            )
            leases = list(
                session.scalars(
                    select(WorkerLease)
                    .where(WorkerLease.tenant_id == tenant_id)
                    .order_by(WorkerLease.worker_id, WorkerLease.heartbeat_at.desc())
                )
            )
            worker_map: dict[str, dict[str, Any]] = {}
            for lease in leases:
                item = worker_map.setdefault(
                    lease.worker_id,
                    {
                        "worker_id": lease.worker_id,
                        "active_leases": 0,
                        "expired_leases": 0,
                        "cancel_requested": 0,
                        "last_heartbeat_at": None,
                        "lease_expires_at": None,
                    },
                )
                heartbeat = as_utc(lease.heartbeat_at)
                expiry = as_utc(lease.lease_expires_at)
                if expiry >= current:
                    item["active_leases"] += 1
                else:
                    item["expired_leases"] += 1
                if lease.cancel_requested:
                    item["cancel_requested"] += 1
                if item["last_heartbeat_at"] is None or heartbeat > item["last_heartbeat_at"]:
                    item["last_heartbeat_at"] = heartbeat
                if item["lease_expires_at"] is None or expiry > item["lease_expires_at"]:
                    item["lease_expires_at"] = expiry
            dead_letters = list(
                session.scalars(
                    select(JobStageRun)
                    .where(
                        JobStageRun.tenant_id == tenant_id,
                        JobStageRun.status == "dead_letter",
                    )
                    .order_by(JobStageRun.created_at.desc(), JobStageRun.id.desc())
                    .limit(20)
                )
            )
            pending_outbox = int(
                session.scalar(
                    select(func.count()).select_from(OutboxEvent).where(
                        OutboxEvent.tenant_id == tenant_id,
                        OutboxEvent.delivered_at.is_(None),
                    )
                )
                or 0
            )
            failed_outbox = int(
                session.scalar(
                    select(func.count()).select_from(OutboxEvent).where(
                        OutboxEvent.tenant_id == tenant_id,
                        OutboxEvent.delivered_at.is_(None),
                        OutboxEvent.last_error.is_not(None),
                    )
                )
                or 0
            )
            waiting_jobs = session.scalars(
                select(Job).where(
                    Job.tenant_id == tenant_id,
                    Job.status == "waiting_approval",
                )
            )
            budget_waiting = sum(
                1
                for job in waiting_jobs
                if job.manifest.get("approval_gate") == "budget"
            )
            return {
                "generated_at": current.isoformat(),
                "jobs_by_status": jobs_by_status,
                "queues": queues,
                "leases": {"active": active_leases, "expired": expired_leases},
                "workers": list(worker_map.values()),
                "recent_dead_letters": [self._stage_dict(run) for run in dead_letters],
                "outbox": {"pending": pending_outbox, "failed": failed_outbox},
                "budget_waiting": budget_waiting,
            }

    def mark_outbox_delivered(self, tenant_id: str, event_id: str, *, delivered_at: datetime | None = None) -> None:
        with self.database.transaction() as session:
            event = session.get(OutboxEvent, (tenant_id, event_id))
            if event is None:
                raise RepositoryNotFound("outbox event not found")
            event.delivered_at = delivered_at or utc_now()
            event.delivery_attempts += 1
            event.last_error = None

    def mark_outbox_failed(self, tenant_id: str, event_id: str, error: str) -> None:
        with self.database.transaction() as session:
            event = session.get(OutboxEvent, (tenant_id, event_id))
            if event is None:
                raise RepositoryNotFound("outbox event not found")
            event.delivery_attempts += 1
            event.last_error = error[:4000]

    def rebuild_queue_outbox(self) -> int:
        rebuilt = 0
        with self.database.transaction() as session:
            queued_runs = list(session.scalars(select(JobStageRun).where(JobStageRun.status == "queued")))
            for run in queued_runs:
                existing = session.scalar(
                    select(OutboxEvent.id).where(
                        OutboxEvent.tenant_id == run.tenant_id,
                        OutboxEvent.topic == f"queue.{run.queue_name}",
                        OutboxEvent.aggregate_id == run.id,
                        OutboxEvent.delivered_at.is_(None),
                    )
                )
                if existing is None:
                    self._enqueue_stage_outbox(session, run)
                    rebuilt += 1
        return rebuilt

    # -- Artifact metadata and transactionally promoted revisions ------------

    def commit_artifact_bundle(
        self,
        tenant_id: str,
        job_id: str,
        *,
        domain: str,
        revision_id: str,
        parent_id: str | None,
        stage_run_id: str | None,
        created_by: str,
        blobs: Sequence[BlobRegistration],
        revision_hash: str,
        make_current: bool,
        manifest: dict[str, Any] | None = None,
        expected_job_version: int | None = None,
        invalidated_stages: Sequence[str] = (),
        event: dict[str, Any] | None = None,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            if expected_job_version is not None and job.row_version != expected_job_version:
                raise RepositoryConflict("job version changed before artifact commit")
            existing = session.get(ArtifactRevision, (tenant_id, revision_id))
            if existing is not None:
                if existing.revision_hash != revision_hash:
                    raise RepositoryConflict("revision ID already exists with different content")
                return self._artifact_revision_dict(existing, self._blobs_for_revision(session, tenant_id, revision_id))
            duplicate = session.scalar(
                select(ArtifactRevision).where(
                    ArtifactRevision.tenant_id == tenant_id,
                    ArtifactRevision.job_id == job_id,
                    ArtifactRevision.domain == domain,
                    ArtifactRevision.revision_hash == revision_hash,
                )
            )
            if duplicate is not None:
                return self._artifact_revision_dict(
                    duplicate,
                    self._blobs_for_revision(session, tenant_id, duplicate.id),
                )
            stage_run: JobStageRun | None = None
            if stage_run_id:
                stage_run = self._require_stage_run(session, tenant_id, stage_run_id, for_update=True)
                if stage_run.job_id != job_id:
                    raise RepositoryNotFound("stage run not found")
            if make_current:
                session.execute(
                    update(ArtifactRevision)
                    .where(
                        ArtifactRevision.tenant_id == tenant_id,
                        ArtifactRevision.job_id == job_id,
                        ArtifactRevision.domain == domain,
                        ArtifactRevision.is_current.is_(True),
                    )
                    .values(is_current=False)
                )
            object_manifest = [
                {
                    "logical_name": item.logical_name,
                    "object_key": item.object_key,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "media_type": item.media_type,
                }
                for item in sorted(blobs, key=lambda item: item.logical_name)
            ]
            revision = ArtifactRevision(
                tenant_id=tenant_id,
                id=revision_id,
                job_id=job_id,
                domain=domain,
                parent_id=parent_id,
                stage_run_id=stage_run_id,
                revision_hash=revision_hash,
                object_manifest=object_manifest,
                created_by=created_by,
                is_current=make_current,
            )
            session.add(revision)
            # The composite revision foreign key is intentionally tenant scoped.
            # Flush the parent first so both SQLite and PostgreSQL enforce the
            # same deterministic insert order without relying on ORM relations.
            session.flush()
            for item in blobs:
                session.add(
                    ArtifactBlob(
                        tenant_id=tenant_id,
                        id=new_id("blob"),
                        job_id=job_id,
                        revision_id=revision_id,
                        logical_name=item.logical_name,
                        object_key=item.object_key,
                        size_bytes=item.size_bytes,
                        sha256=item.sha256,
                        media_type=item.media_type,
                        created_stage=stage_run.stage if stage_run is not None else "migration.import",
                        scan_status=item.scan_status,
                        encryption=copy.deepcopy(item.encryption or {}),
                        pending=False,
                    )
                )
            if stage_run is not None:
                if stage_run.status in {"running", "queued"}:
                    stage_run.status = "succeeded"
                    stage_run.output_hash = revision_hash
                    stage_run.finished_at = utc_now()
                    lease = session.get(WorkerLease, (tenant_id, stage_run_id))
                    if lease is not None:
                        session.delete(lease)
            if invalidated_stages:
                active_runs = list(
                    session.scalars(
                        select(JobStageRun)
                        .where(
                            JobStageRun.tenant_id == tenant_id,
                            JobStageRun.job_id == job_id,
                            JobStageRun.stage.in_(tuple(sorted(set(invalidated_stages)))),
                            JobStageRun.status.in_(tuple(ACTIVE_STAGE_STATUSES)),
                        )
                        .with_for_update()
                    )
                )
                invalidated_at = utc_now()
                for active_run in active_runs:
                    active_run.superseded = True
                    if active_run.status == "queued":
                        active_run.status = "superseded"
                        active_run.finished_at = invalidated_at
            if manifest is not None:
                self._apply_manifest(job, manifest)
            if event is not None:
                self._record_job_event(
                    session,
                    job,
                    event_type=str(event["event_type"]),
                    stage=event.get("stage"),
                    message=str(event["message"]),
                    payload=copy.deepcopy(event.get("payload", {})),
                )
            if audit is not None:
                session.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        id=new_id("aud"),
                        actor_id=str(audit["actor_id"]),
                        action=str(audit["action"]),
                        resource_type=str(audit.get("resource_type", "artifact_revision")),
                        resource_id=str(audit.get("resource_id", revision_id)),
                        result=str(audit.get("result", "succeeded")),
                        request_id=audit.get("request_id"),
                        payload=copy.deepcopy(audit.get("payload", {})),
                    )
                )
            self._add_outbox(
                session,
                tenant_id,
                "artifact.revision.committed",
                "artifact_revision",
                revision_id,
                {
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "revision_id": revision_id,
                    "domain": domain,
                    "revision_hash": revision_hash,
                    "artifact_count": len(blobs),
                },
            )
            session.flush()
            return self._artifact_revision_dict(revision, self._blobs_for_revision(session, tenant_id, revision_id))

    def get_artifact_revision(self, tenant_id: str, revision_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            revision = session.get(ArtifactRevision, (tenant_id, revision_id))
            if revision is None:
                raise RepositoryNotFound("artifact revision not found")
            return self._artifact_revision_dict(
                revision,
                self._blobs_for_revision(session, tenant_id, revision_id),
            )

    def list_artifact_revisions(
        self,
        tenant_id: str,
        job_id: str,
        *,
        domain: str,
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id)
            revisions = list(
                session.scalars(
                    select(ArtifactRevision)
                    .where(
                        ArtifactRevision.tenant_id == tenant_id,
                        ArtifactRevision.job_id == job_id,
                        ArtifactRevision.domain == domain,
                    )
                    .order_by(ArtifactRevision.created_at, ArtifactRevision.id)
                )
            )
            return [
                self._artifact_revision_dict(
                    revision,
                    self._blobs_for_revision(session, tenant_id, revision.id),
                )
                for revision in revisions
            ]

    def get_current_artifact_revision(
        self,
        tenant_id: str,
        job_id: str,
        *,
        domain: str,
    ) -> dict[str, Any]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id)
            revision = session.scalar(
                select(ArtifactRevision).where(
                    ArtifactRevision.tenant_id == tenant_id,
                    ArtifactRevision.job_id == job_id,
                    ArtifactRevision.domain == domain,
                    ArtifactRevision.is_current.is_(True),
                )
            )
            if revision is None:
                raise RepositoryNotFound("current artifact revision not found")
            return self._artifact_revision_dict(
                revision,
                self._blobs_for_revision(session, tenant_id, revision.id),
            )

    def list_job_artifacts(self, tenant_id: str, job_id: str, *, current_only: bool = True) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id)
            statement = (
                select(ArtifactBlob, ArtifactRevision)
                .join(
                    ArtifactRevision,
                    and_(
                        ArtifactRevision.tenant_id == ArtifactBlob.tenant_id,
                        ArtifactRevision.id == ArtifactBlob.revision_id,
                    ),
                )
                .where(ArtifactBlob.tenant_id == tenant_id, ArtifactBlob.job_id == job_id)
            )
            if current_only:
                statement = statement.where(ArtifactRevision.is_current.is_(True))
            rows = session.execute(statement.order_by(ArtifactBlob.logical_name)).all()
            return [self._blob_dict(blob, revision) for blob, revision in rows]

    def get_artifact_blob(self, tenant_id: str, job_id: str, logical_name: str) -> dict[str, Any]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id)
            row = session.execute(
                select(ArtifactBlob, ArtifactRevision)
                .join(
                    ArtifactRevision,
                    and_(
                        ArtifactRevision.tenant_id == ArtifactBlob.tenant_id,
                        ArtifactRevision.id == ArtifactBlob.revision_id,
                    ),
                )
                .where(
                    ArtifactBlob.tenant_id == tenant_id,
                    ArtifactBlob.job_id == job_id,
                    ArtifactBlob.logical_name == logical_name,
                    ArtifactRevision.is_current.is_(True),
                )
            ).first()
            if row is None:
                raise RepositoryNotFound("artifact not found")
            return self._blob_dict(row[0], row[1])

    def get_artifact_blob_by_object_key(
        self,
        tenant_id: str,
        job_id: str,
        object_key: str,
    ) -> dict[str, Any]:
        """Re-authorize a signed download against the current, non-deleted job state."""

        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id)
            row = session.execute(
                select(ArtifactBlob, ArtifactRevision)
                .join(
                    ArtifactRevision,
                    and_(
                        ArtifactRevision.tenant_id == ArtifactBlob.tenant_id,
                        ArtifactRevision.id == ArtifactBlob.revision_id,
                    ),
                )
                .where(
                    ArtifactBlob.tenant_id == tenant_id,
                    ArtifactBlob.job_id == job_id,
                    ArtifactBlob.object_key == object_key,
                    ArtifactRevision.is_current.is_(True),
                )
            ).first()
            if row is None:
                raise RepositoryNotFound("artifact not found")
            return self._blob_dict(row[0], row[1])

    def referenced_object_keys(self) -> set[str]:
        with self.database.session() as session:
            artifact_keys = set(session.scalars(select(ArtifactBlob.object_key)))
            input_keys = set(
                session.scalars(select(JobInput.object_key).where(JobInput.object_key.is_not(None)))
            )
            upload_keys = set(
                session.scalars(select(Upload.object_key).where(Upload.object_key.is_not(None)))
            )
            return {
                str(key)
                for key in artifact_keys | input_keys | upload_keys
                if isinstance(key, str) and key
            }

    def consistency_snapshot(self, tenant_id: str, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=True)
            revisions = list(
                session.scalars(
                    select(ArtifactRevision)
                    .where(ArtifactRevision.tenant_id == tenant_id, ArtifactRevision.job_id == job_id)
                    .order_by(ArtifactRevision.domain, ArtifactRevision.created_at, ArtifactRevision.id)
                )
            )
            blobs = list(
                session.scalars(
                    select(ArtifactBlob)
                    .where(ArtifactBlob.tenant_id == tenant_id, ArtifactBlob.job_id == job_id)
                    .order_by(ArtifactBlob.logical_name, ArtifactBlob.id)
                )
            )
            artifact_index = [
                {
                    "revision_id": blob.revision_id,
                    "logical_name": blob.logical_name,
                    "object_key": blob.object_key,
                    "size_bytes": blob.size_bytes,
                    "sha256": blob.sha256,
                    "media_type": blob.media_type,
                }
                for blob in blobs
            ]
            return {
                "tenant_id": tenant_id,
                "job_id": job_id,
                "row_version": job.row_version,
                "snapshot_sequence": job.event_sequence,
                "manifest": copy.deepcopy(job.manifest),
                "database_manifest_sha256": job.manifest_sha256,
                "revision_count": len(revisions),
                "artifact_count": len(blobs),
                "artifact_index": artifact_index,
                "artifact_index_sha256": sha256_json(artifact_index),
                "revision_hashes": {revision.id: revision.revision_hash for revision in revisions},
            }

    def export_manifest_snapshot(self, tenant_id: str, job_id: str) -> dict[str, Any]:
        snapshot = self.consistency_snapshot(tenant_id, job_id)
        exported = copy.deepcopy(snapshot["manifest"])
        exported["phase_c_snapshot"] = {
            "tenant_id": tenant_id,
            "snapshot_sequence": snapshot["snapshot_sequence"],
            "row_version": snapshot["row_version"],
            "database_manifest_sha256": snapshot["database_manifest_sha256"],
            "revision_count": snapshot["revision_count"],
            "artifact_count": snapshot["artifact_count"],
            "artifact_index_sha256": snapshot["artifact_index_sha256"],
        }
        exported["artifacts"] = snapshot["artifact_index"]
        return exported

    # -- Model provenance and approvals --------------------------------------

    def record_model_run(self, tenant_id: str, record: dict[str, Any]) -> str:
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, record["job_id"])
            registration = ModelRunRegistration(
                id=str(record.get("id") or new_id("mdl")),
                task=str(record["task"]),
                provider=str(record["provider"]),
                model=str(record["model"]),
                route_snapshot=copy.deepcopy(record.get("route_snapshot", {})),
                prompt_version=str(record["prompt_version"]),
                schema_version=str(record["schema_version"]),
                provider_call_id=record.get("provider_call_id"),
                usage=copy.deepcopy(record.get("usage", {})),
                cost_micros=int(record.get("cost_micros", 0)),
                status=str(record.get("status", "succeeded")),
            )
            model_run = self._register_model_run(
                session,
                job,
                registration,
                stage_run_id=record.get("stage_run_id"),
            )
            return model_run.id

    def list_model_runs(
        self,
        tenant_id: str,
        job_id: str,
        *,
        stage_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id, include_deleted=True)
            statement = select(ModelRun).where(
                ModelRun.tenant_id == tenant_id,
                ModelRun.job_id == job_id,
            )
            if stage_run_id is not None:
                statement = statement.where(ModelRun.stage_run_id == stage_run_id)
            rows = session.scalars(statement.order_by(ModelRun.created_at, ModelRun.id))
            return [self._model_run_dict(row) for row in rows]

    def _register_model_run(
        self,
        session: Session,
        job: Job,
        registration: ModelRunRegistration,
        *,
        stage_run_id: str | None,
    ) -> ModelRun:
        if not registration.id or len(registration.id) > 128:
            raise RepositoryError("model run ID must contain 1 to 128 characters")
        if registration.cost_micros < 0:
            raise RepositoryError("model run cost cannot be negative")
        if stage_run_id is not None:
            stage_run = self._require_stage_run(session, job.tenant_id, stage_run_id)
            if stage_run.job_id != job.id:
                raise RepositoryConflict("model run stage belongs to another job")
        existing = session.get(ModelRun, (job.tenant_id, registration.id))
        expected = {
            "job_id": job.id,
            "stage_run_id": stage_run_id,
            "task": registration.task,
            "provider": registration.provider,
            "model": registration.model,
            "route_snapshot": copy.deepcopy(registration.route_snapshot),
            "prompt_version": registration.prompt_version,
            "schema_version": registration.schema_version,
            "provider_call_id": registration.provider_call_id,
            "usage": copy.deepcopy(registration.usage or {}),
            "cost_micros": int(registration.cost_micros),
            "status": registration.status,
        }
        if existing is not None:
            actual = {
                "job_id": existing.job_id,
                "stage_run_id": existing.stage_run_id,
                "task": existing.task,
                "provider": existing.provider,
                "model": existing.model,
                "route_snapshot": copy.deepcopy(existing.route_snapshot),
                "prompt_version": existing.prompt_version,
                "schema_version": existing.schema_version,
                "provider_call_id": existing.provider_call_id,
                "usage": copy.deepcopy(existing.usage),
                "cost_micros": existing.cost_micros,
                "status": existing.status,
            }
            if actual != expected:
                raise RepositoryConflict("model run ID already exists with different content")
            return existing
        model_run = ModelRun(
            tenant_id=job.tenant_id,
            id=registration.id,
            **expected,
        )
        session.add(model_run)
        session.flush()
        return model_run

    def record_approval(
        self,
        tenant_id: str,
        job_id: str,
        *,
        gate: str,
        revision_id: str,
        decision: str,
        actor_id: str,
        reason: str | None,
    ) -> str:
        with self.database.transaction() as session:
            self._require_job(session, tenant_id, job_id)
            session.execute(
                update(Approval)
                .where(
                    Approval.tenant_id == tenant_id,
                    Approval.job_id == job_id,
                    Approval.gate == gate,
                    Approval.is_current.is_(True),
                )
                .values(is_current=False)
            )
            approval_id = new_id("apr")
            session.add(
                Approval(
                    tenant_id=tenant_id,
                    id=approval_id,
                    job_id=job_id,
                    gate=gate,
                    revision_id=revision_id,
                    decision=decision,
                    actor_id=actor_id,
                    reason=reason,
                    is_current=True,
                )
            )
            return approval_id

    def decide_revision(
        self,
        tenant_id: str,
        job_id: str,
        *,
        domain: str,
        manifest_key: str,
        gate: str,
        revision_id: str,
        decision: str,
        actor_id: str,
        reason: str | None,
        manifest: dict[str, Any],
        expected_job_version: int,
        event_type: str,
        event_stage: str,
        event_message: str,
        event_payload: dict[str, Any] | None = None,
        next_stage: str | None = None,
        queue_name: str | None = None,
        stage_input_hash: str | None = None,
        route_snapshot_hash: str | None = None,
        config_snapshot_hash: str | None = None,
        priority: str = "interactive",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Commit a review decision and optional continuation stage atomically."""

        if decision not in {"approved", "rejected"}:
            raise RepositoryError(f"unsupported approval decision: {decision}")
        if next_stage and not all(
            (queue_name, stage_input_hash, route_snapshot_hash, config_snapshot_hash)
        ):
            raise RepositoryError("next-stage queue metadata is incomplete")

        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            if job.row_version != expected_job_version:
                raise RepositoryConflict(
                    f"job version changed: expected {expected_job_version}, current {job.row_version}"
                )
            revision = session.get(ArtifactRevision, (tenant_id, revision_id))
            if (
                revision is None
                or revision.job_id != job_id
                or revision.domain != domain
                or not revision.is_current
                or job.manifest.get("current_revisions", {}).get(manifest_key) != revision_id
            ):
                raise RepositoryConflict("the reviewed revision is no longer current")

            session.execute(
                update(Approval)
                .where(
                    Approval.tenant_id == tenant_id,
                    Approval.job_id == job_id,
                    Approval.gate == gate,
                    Approval.is_current.is_(True),
                )
                .values(is_current=False)
            )
            approval = Approval(
                tenant_id=tenant_id,
                id=new_id("apr"),
                job_id=job_id,
                gate=gate,
                revision_id=revision_id,
                decision=decision,
                actor_id=actor_id,
                reason=reason,
                is_current=True,
            )
            session.add(approval)
            self._apply_manifest(job, manifest)

            stage_run: JobStageRun | None = None
            if next_stage is not None:
                identity = StageIdentity(
                    tenant_id=tenant_id,
                    job_id=job_id,
                    stage=next_stage,
                    input_hash=str(stage_input_hash),
                    route_snapshot_hash=str(route_snapshot_hash),
                    config_snapshot_hash=str(config_snapshot_hash),
                )
                stage_run = self._find_successful_stage(session, identity)
                if stage_run is None:
                    stage_run = self._find_active_stage(session, identity)
                if stage_run is None:
                    latest_attempt = session.scalar(
                        select(func.max(JobStageRun.attempt)).where(
                            JobStageRun.tenant_id == tenant_id,
                            JobStageRun.job_id == job_id,
                            JobStageRun.stage == next_stage,
                        )
                    )
                    stage_run = JobStageRun(
                        tenant_id=tenant_id,
                        id=new_id("run"),
                        job_id=job_id,
                        stage=next_stage,
                        queue_name=str(queue_name),
                        attempt=int(latest_attempt or 0) + 1,
                        retry_cycle=0,
                        cycle_attempt=1,
                        input_hash=str(stage_input_hash),
                        route_snapshot_hash=str(route_snapshot_hash),
                        config_snapshot_hash=str(config_snapshot_hash),
                        expected_job_version=job.row_version,
                        status="queued",
                        priority=priority,
                    )
                    session.add(stage_run)
                    self._enqueue_stage_outbox(session, stage_run)

            self._record_job_event(
                session,
                job,
                event_type=event_type,
                stage=event_stage,
                message=event_message,
                payload=copy.deepcopy(event_payload or {}),
            )
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    id=new_id("aud"),
                    actor_id=actor_id,
                    action=f"review.{decision}",
                    resource_type="artifact_revision",
                    resource_id=revision_id,
                    result="succeeded",
                    request_id=request_id,
                    payload={"job_id": job_id, "domain": domain, "gate": gate},
                )
            )
            session.flush()
            return {
                "approval_id": approval.id,
                "decision": decision,
                "job": self._job_snapshot(job),
                "stage_run": self._stage_dict(stage_run) if stage_run is not None else None,
            }

    # -- Cost, quota, audit, and retention -----------------------------------

    def reserve_cost(
        self,
        tenant_id: str,
        job_id: str,
        *,
        stage_run_id: str | None,
        amount_micros: int,
        provider: str | None,
        usage: dict[str, Any],
        pricing_version: str,
        reference_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if amount_micros < 0:
            raise RepositoryError("reservation must be non-negative")
        current = as_utc(now or utc_now())
        approval_required = False
        reservation: dict[str, Any] | None = None
        with _tenant_quota_lock(tenant_id):
            with self.database.transaction() as session:
                tenant = self._require_tenant(session, tenant_id, for_update=True)
                job = self._require_job(session, tenant_id, job_id, for_update=True)
                existing = self._cost_by_reference(session, tenant_id, reference_id, "reservation")
                if existing is not None:
                    if existing.amount_micros != amount_micros or existing.job_id != job_id:
                        raise RepositoryConflict("cost reference was reused with different reservation data")
                    return self._cost_dict(existing)
                committed = self._tenant_committed_cost(session, tenant_id, current)
                hard_limit = tenant.quotas.get("monthly_cost_micros")
                if hard_limit is not None and committed + amount_micros > int(hard_limit):
                    raise QuotaExceeded("tenant monthly cost quota would be exceeded")
                budget = copy.deepcopy(job.manifest.get("budget", {}))
                budget_limit = budget.get("limit_micros")
                job_spent = self._job_actual_cost(session, tenant_id, job_id)
                job_reserved = self._job_outstanding_reservations(session, tenant_id, job_id)
                projected_total = job_spent + job_reserved + amount_micros
                if budget_limit is not None and projected_total > int(budget_limit):
                    pending = budget.get("pending_request")
                    if isinstance(pending, dict) and pending.get("reference_id") == reference_id:
                        approval_required = True
                        continue_update = False
                    else:
                        continue_update = True
                    if not continue_update:
                        raise BudgetApprovalRequired("job budget approval is required")
                    manifest = copy.deepcopy(job.manifest)
                    budget["pending_request"] = {
                        "request_id": new_id("budget"),
                        "reference_id": reference_id,
                        "stage_run_id": stage_run_id,
                        "requested_micros": amount_micros,
                        "spent_micros": job_spent,
                        "reserved_micros": job_reserved,
                        "projected_total_micros": projected_total,
                        "budget_limit_micros": int(budget_limit),
                        "provider": provider,
                        "usage": copy.deepcopy(usage),
                        "pricing_version": pricing_version,
                        "previous_status": job.status,
                        "previous_display_status": job.manifest.get("display_status"),
                        "previous_stage": job.stage,
                        "requested_at": current.isoformat(),
                    }
                    manifest["budget"] = budget
                    manifest.update(
                        {
                            "status": "waiting_approval",
                            "display_status": "等待预算审批",
                            "approval_gate": "budget",
                            "needs_action": True,
                            "next_action": "批准新增预算或降低生成范围",
                        }
                    )
                    self._apply_manifest(job, manifest)
                    self._record_job_event(
                        session,
                        job,
                        event_type="job.budget_approval_required",
                        stage=job.stage,
                        message="预计费用超过任务预算，等待审批",
                        payload={
                            "reference_id": reference_id,
                            "stage_run_id": stage_run_id,
                            "requested_micros": amount_micros,
                            "projected_total_micros": projected_total,
                            "budget_limit_micros": int(budget_limit),
                        },
                        occurred_at=current,
                    )
                    self._add_outbox(
                        session,
                        tenant_id,
                        "job.budget_approval_required",
                        "job",
                        job_id,
                        {
                            "tenant_id": tenant_id,
                            "job_id": job_id,
                            "reference_id": reference_id,
                            "stage_run_id": stage_run_id,
                            "requested_micros": amount_micros,
                            "projected_total_micros": projected_total,
                            "budget_limit_micros": int(budget_limit),
                        },
                    )
                    approval_required = True
                else:
                    entry = CostLedger(
                        tenant_id=tenant_id,
                        id=new_id("cost"),
                        job_id=job_id,
                        stage_run_id=stage_run_id,
                        kind="reservation",
                        amount_micros=amount_micros,
                        provider=provider,
                        usage=copy.deepcopy(usage),
                        pricing_version=pricing_version,
                        estimated=True,
                        reference_id=reference_id,
                        created_at=current,
                    )
                    session.add(entry)
                    session.flush()
                    reservation = self._cost_dict(entry)
        if approval_required:
            raise BudgetApprovalRequired("job budget approval is required")
        if reservation is None:
            raise RepositoryError("cost reservation was not created")
        return reservation

    def pause_stage_run_for_budget(
        self,
        tenant_id: str,
        stage_run_id: str,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Release a worker lease without retrying while a budget gate is open."""

        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            run = self._require_stage_run(session, tenant_id, stage_run_id, for_update=True)
            job = self._require_job(session, tenant_id, run.job_id, for_update=True)
            self._require_owned_lease(session, run, worker_id, current, allow_expired=True)
            pending = job.manifest.get("budget", {}).get("pending_request")
            if not isinstance(pending, dict) or pending.get("stage_run_id") != stage_run_id:
                raise RepositoryConflict("budget approval request does not match the running stage")
            lease = session.get(WorkerLease, (tenant_id, stage_run_id))
            if lease is not None:
                session.delete(lease)
            run.status = "waiting_approval"
            run.worker_id = None
            run.lease_expires_at = None
            run.heartbeat_at = current
            run.finished_at = current
            run.error_code = "budget_approval_required"
            run.error_message = "stage paused before external spend because job budget approval is required"
            run.retryable = False
            self._add_outbox(
                session,
                tenant_id,
                "stage.budget_approval_required",
                "stage_run",
                stage_run_id,
                {
                    "tenant_id": tenant_id,
                    "job_id": run.job_id,
                    "stage_run_id": stage_run_id,
                    "reference_id": pending.get("reference_id"),
                },
            )
            session.flush()
            return self._stage_dict(run)

    def decide_budget(
        self,
        tenant_id: str,
        job_id: str,
        *,
        decision: str,
        resolution: str | None,
        actor_id: str,
        reason: str | None,
        expected_job_version: int,
        new_limit_micros: int | None = None,
        reduced_scope: dict[str, Any] | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Resolve a budget gate and atomically resume the paused stage."""

        if decision not in {"approved", "rejected"}:
            raise RepositoryError(f"unsupported budget decision: {decision}")
        if decision == "approved" and resolution not in {"raise_limit", "reduce_scope"}:
            raise RepositoryError("approved budget decisions require a supported resolution")
        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            if job.row_version != expected_job_version:
                raise RepositoryConflict(
                    f"job version changed: expected {expected_job_version}, current {job.row_version}"
                )
            manifest = copy.deepcopy(job.manifest)
            budget = copy.deepcopy(manifest.get("budget", {}))
            pending = budget.get("pending_request")
            if not isinstance(pending, dict):
                raise RepositoryConflict("job has no pending budget approval request")
            pending_id = str(pending.get("request_id") or pending.get("reference_id") or "")
            if not pending_id:
                raise RepositoryConflict("pending budget approval request is invalid")

            session.execute(
                update(Approval)
                .where(
                    Approval.tenant_id == tenant_id,
                    Approval.job_id == job_id,
                    Approval.gate == "budget",
                    Approval.is_current.is_(True),
                )
                .values(is_current=False)
            )
            approval = Approval(
                tenant_id=tenant_id,
                id=new_id("apr"),
                job_id=job_id,
                gate="budget",
                revision_id=pending_id,
                decision=decision,
                actor_id=actor_id,
                reason=reason,
                is_current=True,
                created_at=current,
            )
            session.add(approval)

            stage_run: JobStageRun | None = None
            if decision == "approved":
                if resolution == "raise_limit":
                    projected_total = int(pending.get("projected_total_micros") or 0)
                    if new_limit_micros is None or new_limit_micros < projected_total:
                        raise RepositoryConflict(
                            "new budget limit must cover the projected total cost"
                        )
                    budget["limit_micros"] = int(new_limit_micros)
                elif resolution == "reduce_scope":
                    if not isinstance(reduced_scope, dict) or not reduced_scope:
                        raise RepositoryConflict("reduced generation scope is required")
                    manifest["generation_scope"] = copy.deepcopy(reduced_scope)

                history = list(budget.get("approval_history") or [])
                history.append(
                    {
                        "request_id": pending_id,
                        "decision": decision,
                        "resolution": resolution,
                        "actor_id": actor_id,
                        "reason": reason,
                        "new_limit_micros": new_limit_micros,
                        "reduced_scope": copy.deepcopy(reduced_scope),
                        "decided_at": current.isoformat(),
                    }
                )
                budget["approval_history"] = history[-100:]
                budget.pop("pending_request", None)
                manifest["budget"] = budget
                manifest.pop("approval_gate", None)
                manifest.update(
                    {
                        "status": "queued",
                        "display_status": "预算已处理，等待重试",
                        "stage": str(pending.get("previous_stage") or job.stage),
                        "needs_action": False,
                        "next_action": "等待原阶段重新执行",
                        "can_cancel": True,
                    }
                )
                self._apply_manifest(job, manifest)

                stage_run_id = pending.get("stage_run_id")
                if isinstance(stage_run_id, str) and stage_run_id:
                    stage_run = self._require_stage_run(
                        session,
                        tenant_id,
                        stage_run_id,
                        for_update=True,
                    )
                    if stage_run.job_id != job_id or stage_run.status != "waiting_approval":
                        raise RepositoryConflict("budget-paused stage is no longer resumable")
                    stage_run.status = "queued"
                    stage_run.expected_job_version = job.row_version
                    stage_run.worker_id = None
                    stage_run.lease_expires_at = None
                    stage_run.heartbeat_at = None
                    stage_run.started_at = None
                    stage_run.finished_at = None
                    stage_run.error_code = None
                    stage_run.error_message = None
                    stage_run.retryable = True
                    self._enqueue_stage_outbox(session, stage_run)
            else:
                rejected = copy.deepcopy(pending)
                rejected.update(
                    {
                        "decision": "rejected",
                        "reason": reason,
                        "actor_id": actor_id,
                        "decided_at": current.isoformat(),
                    }
                )
                budget["pending_request"] = rejected
                manifest["budget"] = budget
                manifest.update(
                    {
                        "status": "waiting_approval",
                        "display_status": "预算审批未通过",
                        "approval_gate": "budget",
                        "needs_action": True,
                        "next_action": "降低生成范围或由管理员重新审批预算",
                    }
                )
                self._apply_manifest(job, manifest)

            self._record_job_event(
                session,
                job,
                event_type=f"job.budget_{decision}",
                stage=job.stage,
                message="预算审批已通过" if decision == "approved" else "预算审批未通过",
                payload={
                    "request_id": pending_id,
                    "resolution": resolution,
                    "new_limit_micros": new_limit_micros,
                },
                occurred_at=current,
            )
            self._add_outbox(
                session,
                tenant_id,
                f"job.budget_{decision}",
                "job",
                job_id,
                {
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "request_id": pending_id,
                    "resolution": resolution,
                    "stage_run_id": stage_run.id if stage_run is not None else None,
                },
            )
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    id=new_id("aud"),
                    actor_id=actor_id,
                    action=f"budget.{decision}",
                    resource_type="job",
                    resource_id=job_id,
                    result="succeeded",
                    request_id=request_id,
                    payload={
                        "request_id": pending_id,
                        "resolution": resolution,
                        "new_limit_micros": new_limit_micros,
                    },
                    occurred_at=current,
                )
            )
            session.flush()
            return {
                "approval_id": approval.id,
                "decision": decision,
                "resolution": resolution,
                "job": self._job_snapshot(job),
                "stage_run": self._stage_dict(stage_run) if stage_run is not None else None,
            }

    def settle_cost(
        self,
        tenant_id: str,
        job_id: str,
        *,
        reference_id: str,
        actual_micros: int,
        provider: str | None,
        usage: dict[str, Any],
        pricing_version: str,
        estimated: bool = False,
        outcome: str = "succeeded",
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if actual_micros < 0:
            raise RepositoryError("actual cost must be non-negative")
        if outcome not in QUOTA_OUTCOMES - {"released"}:
            raise RepositoryError(f"unsupported cost outcome: {outcome}")
        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, for_update=True)
            reservation = self._cost_by_reference(session, tenant_id, reference_id, "reservation")
            if reservation is None or reservation.job_id != job_id:
                raise RepositoryNotFound("cost reservation not found")
            actual = self._cost_by_reference(session, tenant_id, reference_id, "actual")
            release = self._cost_by_reference(session, tenant_id, reference_id, "release")
            settled_usage = {**copy.deepcopy(usage), "outcome": outcome}
            if actual is None:
                actual = CostLedger(
                    tenant_id=tenant_id,
                    id=new_id("cost"),
                    job_id=job_id,
                    stage_run_id=reservation.stage_run_id,
                    kind="actual",
                    amount_micros=actual_micros,
                    provider=provider,
                    usage=settled_usage,
                    pricing_version=pricing_version,
                    estimated=estimated,
                    reference_id=reference_id,
                    created_at=current,
                )
                session.add(actual)
            elif actual.amount_micros != actual_micros or actual.usage.get("outcome") != outcome:
                raise RepositoryConflict("cost reference was already settled with different actual data")
            if release is None:
                release = CostLedger(
                    tenant_id=tenant_id,
                    id=new_id("cost"),
                    job_id=job_id,
                    stage_run_id=reservation.stage_run_id,
                    kind="release",
                    amount_micros=-reservation.amount_micros,
                    provider=provider,
                    usage={"outcome": outcome},
                    pricing_version=pricing_version,
                    estimated=False,
                    reference_id=reference_id,
                    created_at=current,
                )
                session.add(release)
            session.flush()
            manifest = copy.deepcopy(job.manifest)
            budget = copy.deepcopy(manifest.get("budget", {}))
            budget["spent_micros"] = self._job_actual_cost(session, tenant_id, job_id)
            manifest["budget"] = budget
            self._apply_manifest(job, manifest)
            return [self._cost_dict(reservation), self._cost_dict(actual), self._cost_dict(release)]

    def release_cost(
        self,
        tenant_id: str,
        job_id: str,
        *,
        reference_id: str,
        pricing_version: str,
        outcome: str = "released",
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if outcome not in QUOTA_OUTCOMES:
            raise RepositoryError(f"unsupported cost release outcome: {outcome}")
        settled_outcome = "canceled" if outcome == "released" else outcome
        return self.settle_cost(
            tenant_id,
            job_id,
            reference_id=reference_id,
            actual_micros=0,
            provider=None,
            usage={},
            pricing_version=pricing_version,
            outcome=settled_outcome,
            now=now,
        )

    def cost_ledger(self, tenant_id: str, job_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_job(session, tenant_id, job_id, include_deleted=True)
            entries = session.scalars(
                select(CostLedger)
                .where(CostLedger.tenant_id == tenant_id, CostLedger.job_id == job_id)
                .order_by(CostLedger.created_at, CostLedger.id)
            )
            return [self._cost_dict(entry) for entry in entries]

    def tenant_cost_summary(self, tenant_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        current = as_utc(now or utc_now())
        start, end = self._quota_window_bounds("monthly", current)
        with self.database.session() as session:
            tenant = self._require_tenant(session, tenant_id)
            actual = self._tenant_actual_cost(session, tenant_id, start, end)
            reserved = self._tenant_outstanding_reservations(session, tenant_id)
            return {
                "tenant_id": tenant_id,
                "window": "monthly",
                "window_start": start,
                "window_end": end,
                "actual_micros": actual,
                "reserved_micros": reserved,
                "committed_micros": actual + reserved,
                "limit_micros": tenant.quotas.get("monthly_cost_micros"),
            }

    def reserve_quota(
        self,
        tenant_id: str,
        *,
        dimension: str,
        amount: int,
        reference_id: str,
        job_id: str | None = None,
        stage_run_id: str | None = None,
        mode: str = "consumption",
        window: str = "monthly",
        expires_at: datetime | None = None,
        usage: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if amount < 0:
            raise RepositoryError("quota reservation must be non-negative")
        if mode not in QUOTA_MODES:
            raise RepositoryError(f"unsupported quota mode: {mode}")
        if window not in QUOTA_WINDOWS:
            raise RepositoryError(f"unsupported quota window: {window}")
        if mode == "capacity" and window != "capacity":
            raise RepositoryError("capacity reservations must use the capacity window")
        if mode == "consumption" and window == "capacity":
            raise RepositoryError("consumption reservations cannot use the capacity window")
        current = as_utc(now or utc_now())
        window_start, window_end = self._quota_window_bounds(window, current)
        normalized_expiry = as_utc(expires_at) if expires_at else None
        with _tenant_quota_lock(tenant_id):
            with self.database.transaction() as session:
                tenant = self._require_tenant(session, tenant_id, for_update=True)
                if job_id is not None:
                    self._require_job(session, tenant_id, job_id)
                if stage_run_id is not None:
                    run = self._require_stage_run(session, tenant_id, stage_run_id)
                    if job_id is not None and run.job_id != job_id:
                        raise RepositoryNotFound("stage run not found")
                existing = session.scalar(
                    select(QuotaReservation).where(
                        QuotaReservation.tenant_id == tenant_id,
                        QuotaReservation.dimension == dimension,
                        QuotaReservation.reference_id == reference_id,
                    )
                )
                if existing is not None:
                    if (
                        existing.reserved_amount != amount
                        or existing.mode != mode
                        or existing.window != window
                        or existing.job_id != job_id
                    ):
                        raise RepositoryConflict("quota reference was reused with different reservation data")
                    return self._quota_dict(existing)
                self._expire_quota_reservations(session, tenant_id, current)
                limit = self._quota_limit(tenant.quotas, dimension, window)
                committed = self._quota_committed(
                    session,
                    tenant_id,
                    dimension,
                    mode,
                    window_start,
                    window_end,
                    current,
                )
                if limit is not None and committed + amount > limit:
                    raise QuotaExceeded(
                        f"tenant quota {dimension} would be exceeded: {committed + amount}>{limit}"
                    )
                reservation = QuotaReservation(
                    tenant_id=tenant_id,
                    id=new_id("quota"),
                    job_id=job_id,
                    stage_run_id=stage_run_id,
                    dimension=dimension,
                    mode=mode,
                    window=window,
                    window_start=window_start,
                    window_end=window_end,
                    reserved_amount=amount,
                    status="active",
                    reference_id=reference_id,
                    usage=copy.deepcopy(usage or {}),
                    created_at=current,
                    expires_at=normalized_expiry,
                )
                session.add(reservation)
                session.flush()
                return self._quota_dict(reservation)

    def settle_quota(
        self,
        tenant_id: str,
        *,
        dimension: str,
        reference_id: str,
        actual_amount: int,
        outcome: str = "succeeded",
        usage: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if actual_amount < 0:
            raise RepositoryError("quota actual amount must be non-negative")
        if outcome not in QUOTA_OUTCOMES - {"released"}:
            raise RepositoryError(f"unsupported quota outcome: {outcome}")
        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            reservation = session.scalar(
                select(QuotaReservation)
                .where(
                    QuotaReservation.tenant_id == tenant_id,
                    QuotaReservation.dimension == dimension,
                    QuotaReservation.reference_id == reference_id,
                )
                .with_for_update()
            )
            if reservation is None:
                raise RepositoryNotFound("quota reservation not found")
            if reservation.status != "active":
                if reservation.actual_amount != actual_amount or reservation.outcome != outcome:
                    raise RepositoryConflict("quota reference was already settled differently")
                return self._quota_dict(reservation)
            reservation.actual_amount = actual_amount
            reservation.outcome = outcome
            reservation.usage = {**copy.deepcopy(reservation.usage), **copy.deepcopy(usage or {})}
            reservation.status = "settled" if reservation.mode == "consumption" else "released"
            reservation.settled_at = current
            session.flush()
            return self._quota_dict(reservation)

    def release_quota(
        self,
        tenant_id: str,
        *,
        dimension: str,
        reference_id: str,
        outcome: str = "released",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if outcome not in QUOTA_OUTCOMES:
            raise RepositoryError(f"unsupported quota release outcome: {outcome}")
        current = as_utc(now or utc_now())
        with self.database.transaction() as session:
            reservation = session.scalar(
                select(QuotaReservation)
                .where(
                    QuotaReservation.tenant_id == tenant_id,
                    QuotaReservation.dimension == dimension,
                    QuotaReservation.reference_id == reference_id,
                )
                .with_for_update()
            )
            if reservation is None:
                raise RepositoryNotFound("quota reservation not found")
            if reservation.status == "active":
                reservation.actual_amount = 0
                reservation.status = "released"
                reservation.outcome = outcome
                reservation.settled_at = current
            elif reservation.status != "released" or reservation.outcome != outcome:
                raise RepositoryConflict("quota reference was already finalized differently")
            session.flush()
            return self._quota_dict(reservation)

    def quota_ledger(
        self,
        tenant_id: str,
        *,
        dimension: str | None = None,
        job_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_tenant(session, tenant_id)
            statement = select(QuotaReservation).where(QuotaReservation.tenant_id == tenant_id)
            if dimension is not None:
                statement = statement.where(QuotaReservation.dimension == dimension)
            if job_id is not None:
                self._require_job(session, tenant_id, job_id, include_deleted=True)
                statement = statement.where(QuotaReservation.job_id == job_id)
            rows = session.scalars(statement.order_by(QuotaReservation.created_at, QuotaReservation.id))
            return [self._quota_dict(row) for row in rows]

    def quota_summary(
        self,
        tenant_id: str,
        *,
        dimension: str,
        mode: str,
        window: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = as_utc(now or utc_now())
        window_start, window_end = self._quota_window_bounds(window, current)
        with self.database.session() as session:
            tenant = self._require_tenant(session, tenant_id)
            committed = self._quota_committed(
                session,
                tenant_id,
                dimension,
                mode,
                window_start,
                window_end,
                current,
            )
            limit = self._quota_limit(tenant.quotas, dimension, window)
            return {
                "tenant_id": tenant_id,
                "dimension": dimension,
                "mode": mode,
                "window": window,
                "window_start": window_start,
                "window_end": window_end,
                "committed": committed,
                "limit": limit,
                "available": None if limit is None else max(limit - committed, 0),
            }

    def audit(
        self,
        tenant_id: str,
        *,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        result: str,
        request_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        with self.database.transaction() as session:
            self._require_tenant(session, tenant_id)
            audit_id = new_id("aud")
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    id=audit_id,
                    actor_id=actor_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    result=result,
                    request_id=request_id,
                    payload=copy.deepcopy(payload or {}),
                )
            )
            return audit_id

    def list_audit(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        actor_id: str | None = None,
        result: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            self._require_tenant(session, tenant_id)
            statement = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
            if action is not None:
                statement = statement.where(AuditLog.action == action)
            if resource_type is not None:
                statement = statement.where(AuditLog.resource_type == resource_type)
            if resource_id is not None:
                statement = statement.where(AuditLog.resource_id == resource_id)
            if actor_id is not None:
                statement = statement.where(AuditLog.actor_id == actor_id)
            if result is not None:
                statement = statement.where(AuditLog.result == result)
            if occurred_from is not None:
                statement = statement.where(AuditLog.occurred_at >= as_utc(occurred_from))
            if occurred_to is not None:
                statement = statement.where(AuditLog.occurred_at <= as_utc(occurred_to))
            rows = session.scalars(
                statement.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(
                    max(1, min(limit, 1000))
                ).offset(max(0, offset))
            )
            return [self._audit_dict(row) for row in rows]

    def prune_audit_before(self, tenant_id: str, *, before: datetime) -> int:
        """Delete expired audit rows while preserving legal-hold job evidence."""

        cutoff = as_utc(before)
        with self.database.transaction() as session:
            self._require_tenant(session, tenant_id)
            protected_job_ids = select(Job.id).where(
                Job.tenant_id == tenant_id,
                Job.legal_hold.is_(True),
            )
            rows = list(
                session.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.tenant_id == tenant_id,
                        AuditLog.occurred_at < cutoff,
                        or_(
                            AuditLog.resource_type != "job",
                            AuditLog.resource_id.not_in(protected_job_ids),
                        ),
                    )
                    .with_for_update()
                )
            )
            for row in rows:
                session.delete(row)
            return len(rows)

    def prune_cost_before(self, tenant_id: str, *, before: datetime) -> int:
        """Delete expired cost rows except those attached to legal-hold jobs."""

        cutoff = as_utc(before)
        with self.database.transaction() as session:
            self._require_tenant(session, tenant_id)
            rows = list(
                session.scalars(
                    select(CostLedger)
                    .join(
                        Job,
                        and_(
                            Job.tenant_id == CostLedger.tenant_id,
                            Job.id == CostLedger.job_id,
                        ),
                    )
                    .where(
                        CostLedger.tenant_id == tenant_id,
                        CostLedger.created_at < cutoff,
                        Job.legal_hold.is_(False),
                    )
                    .with_for_update()
                )
            )
            for row in rows:
                session.delete(row)
            return len(rows)

    def mark_job_deleted(
        self,
        tenant_id: str,
        job_id: str,
        *,
        recovery_days: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=True, for_update=True)
            if job.legal_hold:
                raise RepositoryConflict("job is protected by legal hold")
            job.deleted_at = current
            job.purge_after = current + timedelta(days=recovery_days)
            manifest = copy.deepcopy(job.manifest)
            manifest["lifecycle"] = {
                **copy.deepcopy(manifest.get("lifecycle", {})),
                "deleted_at": current.isoformat(),
                "purge_after": job.purge_after.isoformat(),
            }
            self._apply_manifest(job, manifest)
            return self._job_snapshot(job)

    def restore_deleted_job(self, tenant_id: str, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or utc_now()
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=True, for_update=True)
            if job.deleted_at is None:
                return self._job_snapshot(job)
            if job.purge_after is not None and as_utc(job.purge_after) <= current:
                raise RepositoryConflict("job recovery window has expired")
            job.deleted_at = None
            job.purge_after = None
            manifest = copy.deepcopy(job.manifest)
            manifest.pop("lifecycle", None)
            self._apply_manifest(job, manifest)
            return self._job_snapshot(job)

    def set_job_protection(
        self,
        tenant_id: str,
        job_id: str,
        *,
        pinned: bool | None = None,
        legal_hold: bool | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=True, for_update=True)
            next_pinned = job.pinned if pinned is None else pinned
            next_legal_hold = job.legal_hold if legal_hold is None else legal_hold
            job.pinned = next_pinned
            job.legal_hold = next_legal_hold
            manifest = copy.deepcopy(job.manifest)
            manifest["protection"] = {
                "pinned": next_pinned,
                "legal_hold": next_legal_hold,
            }
            self._apply_manifest(job, manifest)
            return self._job_snapshot(job)

    def apply_retention(
        self,
        tenant_id: str,
        *,
        now: datetime,
        succeeded_days: int,
        failed_days: int,
        recovery_days: int,
    ) -> dict[str, list[str]]:
        current = as_utc(now)
        hidden: list[str] = []
        purge_ready: list[str] = []
        with self.database.transaction() as session:
            jobs = list(
                session.scalars(
                    select(Job).where(Job.tenant_id == tenant_id).with_for_update()
                )
            )
            for job in jobs:
                if job.pinned or job.legal_hold:
                    continue
                if job.deleted_at is None:
                    age = current - as_utc(job.updated_at)
                    retention_days = succeeded_days if job.status == "succeeded" else failed_days
                    if job.status in TERMINAL_JOB_STATUSES and age >= timedelta(days=retention_days):
                        job.deleted_at = current
                        job.purge_after = current + timedelta(days=recovery_days)
                        hidden.append(job.id)
                elif job.purge_after is not None and as_utc(job.purge_after) <= current:
                    purge_ready.append(job.id)
        return {"hidden": hidden, "purge_ready": purge_ready}

    def purge_job_objects_metadata(
        self,
        tenant_id: str,
        job_id: str,
        *,
        now: datetime | None = None,
    ) -> list[str]:
        current = now or utc_now()
        with self.database.transaction() as session:
            job = self._require_job(session, tenant_id, job_id, include_deleted=True, for_update=True)
            if job.deleted_at is None or job.purge_after is None or as_utc(job.purge_after) > current:
                raise RepositoryConflict("job is not ready for permanent deletion")
            if job.pinned or job.legal_hold:
                raise RepositoryConflict("job is protected from permanent deletion")
            blobs = list(
                session.scalars(
                    select(ArtifactBlob).where(
                        ArtifactBlob.tenant_id == tenant_id,
                        ArtifactBlob.job_id == job_id,
                    )
                )
            )
            job_inputs = list(
                session.scalars(
                    select(JobInput).where(
                        JobInput.tenant_id == tenant_id,
                        JobInput.job_id == job_id,
                    )
                )
            )
            uploads = list(
                session.scalars(
                    select(Upload).where(
                        Upload.tenant_id == tenant_id,
                        Upload.bound_job_id == job_id,
                    )
                )
            )
            keys = {
                key
                for key in (
                    [blob.object_key for blob in blobs]
                    + [item.object_key for item in job_inputs]
                    + [upload.object_key for upload in uploads]
                )
                if key
            }
            for blob in blobs:
                session.delete(blob)
            revisions = list(
                session.scalars(
                    select(ArtifactRevision).where(
                        ArtifactRevision.tenant_id == tenant_id,
                        ArtifactRevision.job_id == job_id,
                    )
                )
            )
            for revision in revisions:
                session.delete(revision)
            for job_input in job_inputs:
                session.delete(job_input)
            for upload in uploads:
                for dimension, suffix in (("upload_bytes", "bytes"), ("upload_files", "files")):
                    reservation = session.scalar(
                        select(QuotaReservation)
                        .where(
                            QuotaReservation.tenant_id == tenant_id,
                            QuotaReservation.dimension == dimension,
                            QuotaReservation.reference_id == f"upload:{upload.id}:{suffix}",
                        )
                        .with_for_update()
                    )
                    if reservation is not None and reservation.status == "active":
                        reservation.actual_amount = 0
                        reservation.status = "released"
                        reservation.outcome = "released"
                        reservation.settled_at = current
                session.delete(upload)
            manifest = copy.deepcopy(job.manifest)
            manifest["lifecycle"] = {
                **copy.deepcopy(manifest.get("lifecycle", {})),
                "purged_at": current.isoformat(),
                "object_count": len(keys),
            }
            self._apply_manifest(job, manifest)
            return sorted(keys)

    # -- Internal helpers -----------------------------------------------------

    def _require_tenant(self, session: Session, tenant_id: str, *, for_update: bool = False) -> Tenant:
        statement = select(Tenant).where(Tenant.id == tenant_id)
        if for_update:
            statement = statement.with_for_update()
        tenant = session.scalar(statement)
        if tenant is None or tenant.status != "active":
            raise RepositoryNotFound("tenant not found")
        return tenant

    def _lock_tenant_quota(
        self,
        session: Session,
        tenant_id: str,
        tenant: Tenant | None = None,
    ) -> Tenant:
        """Serialize a tenant quota decision without serializing the whole job transaction.

        SQLite relies on the process guard held by callers. PostgreSQL uses a
        transaction-scoped advisory lock acquired immediately before the quota
        read/write section. This keeps concurrent job-envelope inserts
        independent while preserving one authoritative quota decision per
        tenant at commit time.
        """

        if self.database.engine.dialect.name == "sqlite":
            return tenant or self._require_tenant(session, tenant_id)
        lock_id = int.from_bytes(
            hashlib.sha256(f"tenant-quota:{tenant_id}".encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        session.execute(select(func.pg_advisory_xact_lock(lock_id)))
        if tenant is not None:
            session.expire(tenant, ["status", "quotas"])
            if tenant.status != "active":
                raise RepositoryNotFound("tenant not found")
            return tenant
        return self._require_tenant(session, tenant_id)

    def _require_job(
        self,
        session: Session,
        tenant_id: str,
        job_id: str,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Job:
        statement = select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
        if not include_deleted:
            statement = statement.where(Job.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        job = session.scalar(statement)
        if job is None:
            raise RepositoryNotFound("job not found")
        return job

    def _require_stage_run(
        self,
        session: Session,
        tenant_id: str,
        stage_run_id: str,
        *,
        for_update: bool = False,
    ) -> JobStageRun:
        statement = select(JobStageRun).where(
            JobStageRun.tenant_id == tenant_id,
            JobStageRun.id == stage_run_id,
        )
        if for_update:
            statement = statement.with_for_update()
        run = session.scalar(statement)
        if run is None:
            raise RepositoryNotFound("stage run not found")
        return run

    def _find_successful_stage(
        self,
        session: Session,
        identity: StageIdentity,
        *,
        exclude_id: str | None = None,
    ) -> JobStageRun | None:
        statement = select(JobStageRun).where(
            JobStageRun.tenant_id == identity.tenant_id,
            JobStageRun.job_id == identity.job_id,
            JobStageRun.stage == identity.stage,
            JobStageRun.input_hash == identity.input_hash,
            JobStageRun.route_snapshot_hash == identity.route_snapshot_hash,
            JobStageRun.config_snapshot_hash == identity.config_snapshot_hash,
            JobStageRun.status == "succeeded",
            JobStageRun.superseded.is_(False),
        )
        if exclude_id:
            statement = statement.where(JobStageRun.id != exclude_id)
        return session.scalar(statement.order_by(JobStageRun.finished_at.desc()).limit(1))

    def _find_active_stage(
        self,
        session: Session,
        identity: StageIdentity,
        *,
        exclude_id: str | None = None,
        statuses: Sequence[str] = ("queued", "running"),
    ) -> JobStageRun | None:
        statement = select(JobStageRun).where(
            JobStageRun.tenant_id == identity.tenant_id,
            JobStageRun.job_id == identity.job_id,
            JobStageRun.stage == identity.stage,
            JobStageRun.input_hash == identity.input_hash,
            JobStageRun.route_snapshot_hash == identity.route_snapshot_hash,
            JobStageRun.config_snapshot_hash == identity.config_snapshot_hash,
            JobStageRun.status.in_(tuple(statuses)),
            JobStageRun.superseded.is_(False),
        )
        if exclude_id:
            statement = statement.where(JobStageRun.id != exclude_id)
        return session.scalar(statement.order_by(JobStageRun.attempt).limit(1))

    def _require_owned_lease(
        self,
        session: Session,
        run: JobStageRun,
        worker_id: str,
        now: datetime,
        *,
        allow_expired: bool = False,
    ) -> WorkerLease:
        lease = session.get(WorkerLease, (run.tenant_id, run.id))
        if run.status != "running" or lease is None or lease.worker_id != worker_id:
            raise LeaseConflict("worker does not own this running stage")
        if not allow_expired and as_utc(lease.lease_expires_at) <= now:
            raise LeaseConflict("worker lease expired before commit")
        return lease

    def _enqueue_stage_outbox(self, session: Session, run: JobStageRun) -> None:
        self._add_outbox(
            session,
            run.tenant_id,
            f"queue.{run.queue_name}",
            "stage_run",
            run.id,
            {
                "message_version": 1,
                "tenant_id": run.tenant_id,
                "job_id": run.job_id,
                "stage_run_id": run.id,
                "expected_job_version": run.expected_job_version,
                "input_snapshot_hash": run.input_hash,
                "priority": run.priority,
                "enqueued_at": utc_now().isoformat(),
            },
        )

    def _add_outbox(
        self,
        session: Session,
        tenant_id: str,
        topic: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        event = OutboxEvent(
            tenant_id=tenant_id,
            id=new_id("out"),
            topic=topic,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=copy.deepcopy(payload),
        )
        session.add(event)
        return event

    def _apply_manifest(self, job: Job, manifest: dict[str, Any]) -> None:
        manifest_copy = copy.deepcopy(manifest)
        job.manifest = manifest_copy
        job.manifest_sha256 = sha256_json(manifest_copy)
        job.project_name = manifest_copy["project_name"]
        job.status = manifest_copy["status"]
        job.stage = manifest_copy["stage"]
        job.input_mode = manifest_copy.get("input_mode", job.input_mode)
        job.approval_mode = manifest_copy.get("approval_mode", job.approval_mode)
        job.row_version += 1
        job.updated_at = utc_now()

    def _record_job_event(
        self,
        session: Session,
        job: Job,
        *,
        event_type: str,
        stage: str | None,
        message: str,
        payload: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> JobEvent:
        job.event_sequence += 1
        event = JobEvent(
            tenant_id=job.tenant_id,
            job_id=job.id,
            sequence=job.event_sequence,
            event_type=event_type,
            stage=stage,
            message=message,
            payload=copy.deepcopy(payload or {}),
            occurred_at=occurred_at or utc_now(),
        )
        session.add(event)
        self._add_outbox(
            session,
            job.tenant_id,
            "job.event",
            "job",
            job.id,
            {
                "tenant_id": job.tenant_id,
                "job_id": job.id,
                "sequence": job.event_sequence,
                "event_type": event_type,
            },
        )
        return event

    def _release_job_capacity(
        self,
        session: Session,
        tenant_id: str,
        job_id: str,
        outcome: str,
        current: datetime,
    ) -> None:
        reservation = session.scalar(
            select(QuotaReservation)
            .where(
                QuotaReservation.tenant_id == tenant_id,
                QuotaReservation.dimension == "active_jobs",
                QuotaReservation.reference_id == f"job:{job_id}:active",
            )
            .with_for_update()
        )
        if reservation is not None and reservation.status == "active":
            reservation.actual_amount = 0
            reservation.status = "released"
            reservation.outcome = outcome if outcome in QUOTA_OUTCOMES else "released"
            reservation.settled_at = current

    def _activate_job_capacity(
        self,
        session: Session,
        tenant: Tenant,
        job_id: str,
        current: datetime,
    ) -> None:
        reference = f"job:{job_id}:active"
        reservation = session.scalar(
            select(QuotaReservation)
            .where(
                QuotaReservation.tenant_id == tenant.id,
                QuotaReservation.dimension == "active_jobs",
                QuotaReservation.reference_id == reference,
            )
            .with_for_update()
        )
        if reservation is not None and reservation.status == "active":
            return
        self._expire_quota_reservations(session, tenant.id, current)
        limit = self._quota_limit(tenant.quotas, "active_jobs", "capacity")
        committed = self._quota_committed(
            session,
            tenant.id,
            "active_jobs",
            "capacity",
            None,
            None,
            current,
        )
        if limit is not None and committed + 1 > limit:
            raise QuotaExceeded(
                f"tenant quota active_jobs would be exceeded: {committed + 1}>{limit}"
            )
        if reservation is None:
            session.add(
                QuotaReservation(
                    tenant_id=tenant.id,
                    id=new_id("quota"),
                    job_id=job_id,
                    dimension="active_jobs",
                    mode="capacity",
                    window="capacity",
                    reserved_amount=1,
                    status="active",
                    reference_id=reference,
                    usage={"source": "job.retry"},
                    created_at=current,
                )
            )
            return
        reservation.actual_amount = None
        reservation.status = "active"
        reservation.outcome = None
        reservation.settled_at = None
        reservation.expires_at = None
        reservation.usage = {**copy.deepcopy(reservation.usage), "reactivated_by": "job.retry"}

    def _finalize_job_cancellation(
        self,
        session: Session,
        job: Job,
        current: datetime,
    ) -> bool:
        remaining = session.scalar(
            select(func.count())
            .select_from(WorkerLease)
            .where(WorkerLease.tenant_id == job.tenant_id, WorkerLease.job_id == job.id)
        )
        if int(remaining or 0) > 0:
            return False
        if job.status == "canceled":
            self._release_job_capacity(session, job.tenant_id, job.id, "canceled", current)
            return True
        manifest = copy.deepcopy(job.manifest)
        manifest.update(
            {
                "status": "canceled",
                "display_status": "已取消",
                "cancel_requested": True,
                "can_cancel": False,
                "can_retry": True,
                "needs_action": False,
                "next_action": "可显式恢复任务",
            }
        )
        self._apply_manifest(job, manifest)
        self._release_job_capacity(session, job.tenant_id, job.id, "canceled", current)
        self._record_job_event(
            session,
            job,
            event_type="job.canceled",
            stage=job.stage,
            message="任务取消完成，运行租约和子任务均已释放",
            payload={},
            occurred_at=current,
        )
        return True

    def _identity_from_run(self, run: JobStageRun) -> StageIdentity:
        return StageIdentity(
            tenant_id=run.tenant_id,
            job_id=run.job_id,
            stage=run.stage,
            input_hash=run.input_hash,
            route_snapshot_hash=run.route_snapshot_hash,
            config_snapshot_hash=run.config_snapshot_hash,
        )

    def _blobs_for_revision(self, session: Session, tenant_id: str, revision_id: str) -> list[ArtifactBlob]:
        return list(
            session.scalars(
                select(ArtifactBlob)
                .where(ArtifactBlob.tenant_id == tenant_id, ArtifactBlob.revision_id == revision_id)
                .order_by(ArtifactBlob.logical_name)
            )
        )

    def _cost_by_reference(
        self,
        session: Session,
        tenant_id: str,
        reference_id: str,
        kind: str,
    ) -> CostLedger | None:
        return session.scalar(
            select(CostLedger).where(
                CostLedger.tenant_id == tenant_id,
                CostLedger.reference_id == reference_id,
                CostLedger.kind == kind,
            )
        )

    def _tenant_committed_cost(self, session: Session, tenant_id: str, now: datetime) -> int:
        start, end = self._quota_window_bounds("monthly", now)
        return self._tenant_actual_cost(session, tenant_id, start, end) + self._tenant_outstanding_reservations(
            session, tenant_id
        )

    def _tenant_actual_cost(
        self,
        session: Session,
        tenant_id: str,
        window_start: datetime | None,
        window_end: datetime | None,
    ) -> int:
        statement = select(func.coalesce(func.sum(CostLedger.amount_micros), 0)).where(
            CostLedger.tenant_id == tenant_id,
            CostLedger.kind == "actual",
        )
        if window_start is not None:
            statement = statement.where(CostLedger.created_at >= window_start)
        if window_end is not None:
            statement = statement.where(CostLedger.created_at < window_end)
        return int(session.scalar(statement) or 0)

    def _tenant_outstanding_reservations(self, session: Session, tenant_id: str) -> int:
        released_references = select(CostLedger.reference_id).where(
            CostLedger.tenant_id == tenant_id,
            CostLedger.kind == "release",
            CostLedger.reference_id.is_not(None),
        )
        return int(
            session.scalar(
                select(func.coalesce(func.sum(CostLedger.amount_micros), 0)).where(
                    CostLedger.tenant_id == tenant_id,
                    CostLedger.kind == "reservation",
                    CostLedger.reference_id.is_not(None),
                    CostLedger.reference_id.not_in(released_references),
                )
            )
            or 0
        )

    def _job_actual_cost(self, session: Session, tenant_id: str, job_id: str) -> int:
        return int(
            session.scalar(
                select(func.coalesce(func.sum(CostLedger.amount_micros), 0)).where(
                    CostLedger.tenant_id == tenant_id,
                    CostLedger.job_id == job_id,
                    CostLedger.kind == "actual",
                )
            )
            or 0
        )

    def _job_outstanding_reservations(self, session: Session, tenant_id: str, job_id: str) -> int:
        return int(
            session.scalar(
                select(func.coalesce(func.sum(CostLedger.amount_micros), 0)).where(
                    CostLedger.tenant_id == tenant_id,
                    CostLedger.job_id == job_id,
                    CostLedger.kind.in_(("reservation", "release")),
                )
            )
            or 0
        )

    def _expire_quota_reservations(self, session: Session, tenant_id: str, now: datetime) -> None:
        expired = list(
            session.scalars(
                select(QuotaReservation).where(
                    QuotaReservation.tenant_id == tenant_id,
                    QuotaReservation.status == "active",
                    QuotaReservation.expires_at.is_not(None),
                    QuotaReservation.expires_at <= now,
                )
            )
        )
        for reservation in expired:
            reservation.status = "released"
            reservation.actual_amount = 0
            reservation.outcome = "released"
            reservation.settled_at = now

    def _quota_committed(
        self,
        session: Session,
        tenant_id: str,
        dimension: str,
        mode: str,
        window_start: datetime | None,
        window_end: datetime | None,
        now: datetime,
    ) -> int:
        if mode not in QUOTA_MODES:
            raise RepositoryError(f"unsupported quota mode: {mode}")
        base = [
            QuotaReservation.tenant_id == tenant_id,
            QuotaReservation.dimension == dimension,
            QuotaReservation.mode == mode,
        ]
        if window_start is None:
            base.append(QuotaReservation.window_start.is_(None))
        else:
            base.append(QuotaReservation.window_start == window_start)
        if window_end is None:
            base.append(QuotaReservation.window_end.is_(None))
        else:
            base.append(QuotaReservation.window_end == window_end)
        active = int(
            session.scalar(
                select(func.coalesce(func.sum(QuotaReservation.reserved_amount), 0)).where(
                    *base,
                    QuotaReservation.status == "active",
                    or_(
                        QuotaReservation.expires_at.is_(None),
                        QuotaReservation.expires_at > now,
                    ),
                )
            )
            or 0
        )
        if mode == "capacity":
            return active
        actual = int(
            session.scalar(
                select(func.coalesce(func.sum(QuotaReservation.actual_amount), 0)).where(
                    *base,
                    QuotaReservation.status == "settled",
                )
            )
            or 0
        )
        return active + actual

    @staticmethod
    def _quota_limit(quotas: dict[str, Any], dimension: str, window: str) -> int | None:
        candidates = (
            quotas.get(dimension),
            quotas.get(f"{dimension}_{window}"),
            quotas.get(f"{window}_{dimension}"),
        )
        for candidate in candidates:
            value = candidate
            if isinstance(candidate, dict):
                value = candidate.get(window, candidate.get("limit"))
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RepositoryError(f"quota {dimension} must be numeric")
            if value < 0:
                raise RepositoryError(f"quota {dimension} must be non-negative")
            return int(value)
        return None

    @staticmethod
    def _quota_window_bounds(window: str, now: datetime) -> tuple[datetime | None, datetime | None]:
        current = as_utc(now)
        if window == "daily":
            start = current.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)
        if window == "monthly":
            start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
            return start, end
        if window in {"lifetime", "capacity"}:
            return None, None
        raise RepositoryError(f"unsupported quota window: {window}")

    @staticmethod
    def _config_snapshot_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "manifest_version": manifest.get("manifest_version"),
            "contract_versions": copy.deepcopy(manifest.get("contract_versions", {})),
            "prompt_pins": copy.deepcopy(manifest.get("prompt_pins", {})),
            "task_registry": copy.deepcopy(manifest.get("task_registry", {})),
        }

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _tenant_dict(tenant: Tenant) -> dict[str, Any]:
        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
            "policy": copy.deepcopy(tenant.policy),
            "quotas": copy.deepcopy(tenant.quotas),
            "retention": copy.deepcopy(tenant.retention),
        }

    @staticmethod
    def _upload_dict(upload: Upload) -> dict[str, Any]:
        return {
            "tenant_id": upload.tenant_id,
            "upload_id": upload.id,
            "filename": upload.filename,
            "safe_name": upload.safe_name,
            "declared_size_bytes": upload.declared_size_bytes,
            "size_bytes": upload.size_bytes,
            "declared_media_type": upload.declared_media_type,
            "detected_media_type": upload.detected_media_type,
            "sha256": upload.sha256,
            "object_key": upload.object_key,
            "status": upload.status,
            "scan_status": upload.scan_status,
            "bound_job_id": upload.bound_job_id,
            "metadata": copy.deepcopy(upload.metadata_json),
            "created_at": upload.created_at,
            "expires_at": upload.expires_at,
            "completed_at": upload.completed_at,
            "bound_at": upload.bound_at,
        }

    @staticmethod
    def _job_input_dict(job_input: JobInput) -> dict[str, Any]:
        metadata = copy.deepcopy(job_input.metadata_json)
        return {
            "tenant_id": job_input.tenant_id,
            "input_id": job_input.id,
            "job_id": job_input.job_id,
            "kind": job_input.kind,
            "upload_id": metadata.get("upload_id"),
            "object_key": job_input.object_key,
            "sha256": job_input.sha256,
            "size_bytes": job_input.size_bytes,
            "media_type": job_input.media_type,
            "extraction_status": job_input.extraction_status,
            "outbound_policy": copy.deepcopy(job_input.outbound_policy),
            "metadata": metadata,
            "created_at": job_input.created_at,
        }

    @staticmethod
    def _user_dict(user: User) -> dict[str, Any]:
        return {
            "user_id": user.id,
            "oidc_subject": user.oidc_subject,
            "email": user.email,
            "display_name": user.display_name,
            "disabled": user.disabled,
        }

    @staticmethod
    def _job_snapshot(job: Job) -> dict[str, Any]:
        manifest = copy.deepcopy(job.manifest)
        manifest["row_version"] = job.row_version
        manifest["snapshot_sequence"] = job.event_sequence
        manifest["database_manifest_sha256"] = job.manifest_sha256
        manifest["deleted_at"] = (
            as_utc(job.deleted_at).isoformat().replace("+00:00", "Z")
            if job.deleted_at is not None
            else None
        )
        manifest["purge_after"] = (
            as_utc(job.purge_after).isoformat().replace("+00:00", "Z")
            if job.purge_after is not None
            else None
        )
        manifest["pinned"] = job.pinned
        manifest["legal_hold"] = job.legal_hold
        return manifest

    @staticmethod
    def _event_dict(event: JobEvent) -> dict[str, Any]:
        timestamp = as_utc(event.occurred_at).isoformat().replace("+00:00", "Z")
        return {
            "seq": event.sequence,
            "event_id": event.sequence,
            "job_id": event.job_id,
            "timestamp": timestamp,
            "occurred_at": timestamp,
            "type": event.event_type,
            "stage": event.stage,
            "message": event.message,
            "data": copy.deepcopy(event.payload),
        }

    @staticmethod
    def _stage_dict(run: JobStageRun) -> dict[str, Any]:
        return {
            "tenant_id": run.tenant_id,
            "stage_run_id": run.id,
            "job_id": run.job_id,
            "stage": run.stage,
            "queue_name": run.queue_name,
            "attempt": run.attempt,
            "retry_cycle": run.retry_cycle,
            "cycle_attempt": run.cycle_attempt,
            "input_hash": run.input_hash,
            "route_snapshot_hash": run.route_snapshot_hash,
            "config_snapshot_hash": run.config_snapshot_hash,
            "expected_job_version": run.expected_job_version,
            "status": run.status,
            "priority": run.priority,
            "worker_id": run.worker_id,
            "lease_expires_at": run.lease_expires_at,
            "heartbeat_at": run.heartbeat_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_at": run.created_at,
            "output_hash": run.output_hash,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "retryable": run.retryable,
            "superseded": run.superseded,
            "paid_result_key": run.paid_result_key,
        }

    @staticmethod
    def _artifact_revision_dict(
        revision: ArtifactRevision,
        blobs: Iterable[ArtifactBlob],
    ) -> dict[str, Any]:
        return {
            "tenant_id": revision.tenant_id,
            "revision_id": revision.id,
            "job_id": revision.job_id,
            "domain": revision.domain,
            "parent_id": revision.parent_id,
            "stage_run_id": revision.stage_run_id,
            "revision_hash": revision.revision_hash,
            "is_current": revision.is_current,
            "created_by": revision.created_by,
            "created_at": revision.created_at,
            "artifacts": [
                {
                    "blob_id": blob.id,
                    "logical_name": blob.logical_name,
                    "object_key": blob.object_key,
                    "size_bytes": blob.size_bytes,
                    "sha256": blob.sha256,
                    "media_type": blob.media_type,
                    "scan_status": blob.scan_status,
                }
                for blob in blobs
            ],
        }

    @staticmethod
    def _model_run_dict(model_run: ModelRun) -> dict[str, Any]:
        return {
            "tenant_id": model_run.tenant_id,
            "model_run_id": model_run.id,
            "job_id": model_run.job_id,
            "stage_run_id": model_run.stage_run_id,
            "task": model_run.task,
            "provider": model_run.provider,
            "model": model_run.model,
            "route_snapshot": copy.deepcopy(model_run.route_snapshot),
            "prompt_version": model_run.prompt_version,
            "schema_version": model_run.schema_version,
            "provider_call_id": model_run.provider_call_id,
            "usage": copy.deepcopy(model_run.usage),
            "cost_micros": model_run.cost_micros,
            "status": model_run.status,
            "created_at": model_run.created_at,
        }

    @staticmethod
    def _blob_dict(blob: ArtifactBlob, revision: ArtifactRevision) -> dict[str, Any]:
        return {
            "blob_id": blob.id,
            "tenant_id": blob.tenant_id,
            "job_id": blob.job_id,
            "revision_id": blob.revision_id,
            "domain": revision.domain,
            "logical_name": blob.logical_name,
            "object_key": blob.object_key,
            "size_bytes": blob.size_bytes,
            "sha256": blob.sha256,
            "media_type": blob.media_type,
            "scan_status": blob.scan_status,
            "current": revision.is_current,
        }

    @staticmethod
    def _outbox_dict(event: OutboxEvent) -> dict[str, Any]:
        return {
            "tenant_id": event.tenant_id,
            "event_id": event.id,
            "topic": event.topic,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "payload": copy.deepcopy(event.payload),
            "delivery_attempts": event.delivery_attempts,
            "last_error": event.last_error,
            "created_at": event.created_at,
        }

    @staticmethod
    def _cost_dict(entry: CostLedger) -> dict[str, Any]:
        return {
            "ledger_id": entry.id,
            "tenant_id": entry.tenant_id,
            "job_id": entry.job_id,
            "stage_run_id": entry.stage_run_id,
            "kind": entry.kind,
            "amount_micros": entry.amount_micros,
            "currency": entry.currency,
            "provider": entry.provider,
            "usage": copy.deepcopy(entry.usage),
            "pricing_version": entry.pricing_version,
            "estimated": entry.estimated,
            "reference_id": entry.reference_id,
            "created_at": entry.created_at,
        }

    @staticmethod
    def _quota_dict(entry: QuotaReservation) -> dict[str, Any]:
        return {
            "reservation_id": entry.id,
            "tenant_id": entry.tenant_id,
            "job_id": entry.job_id,
            "stage_run_id": entry.stage_run_id,
            "dimension": entry.dimension,
            "mode": entry.mode,
            "window": entry.window,
            "window_start": entry.window_start,
            "window_end": entry.window_end,
            "reserved_amount": entry.reserved_amount,
            "actual_amount": entry.actual_amount,
            "status": entry.status,
            "outcome": entry.outcome,
            "reference_id": entry.reference_id,
            "usage": copy.deepcopy(entry.usage),
            "created_at": entry.created_at,
            "settled_at": entry.settled_at,
            "expires_at": entry.expires_at,
        }

    @staticmethod
    def _audit_dict(entry: AuditLog) -> dict[str, Any]:
        return {
            "audit_id": entry.id,
            "tenant_id": entry.tenant_id,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "result": entry.result,
            "request_id": entry.request_id,
            "payload": copy.deepcopy(entry.payload),
            "occurred_at": entry.occurred_at,
        }
