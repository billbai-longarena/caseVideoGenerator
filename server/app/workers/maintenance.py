from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from server.app.core.config import Settings, load_settings
from server.app.persistence.database import Database
from server.app.persistence.object_store import ObjectStore, object_store_from_settings
from server.app.persistence.repository import PhaseCRepository, as_utc


LOGGER = logging.getLogger("case-video-maintenance-worker")


@dataclass
class StopSignal:
    requested: bool = False

    def install(self) -> None:
        def stop(_: int, __: object) -> None:
            self.requested = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)


@dataclass
class TenantMaintenanceReport:
    tenant_id: str
    expired_uploads: int = 0
    hidden_jobs: int = 0
    purged_jobs: int = 0
    deleted_objects: int = 0
    pruned_audit_rows: int = 0
    pruned_cost_rows: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


@dataclass
class MaintenanceReport:
    started_at: str
    finished_at: str = ""
    tenants: list[TenantMaintenanceReport] = field(default_factory=list)
    orphan_objects_deleted: int = 0
    orphan_failures: list[dict[str, str]] = field(default_factory=list)

    @property
    def failure_count(self) -> int:
        return sum(len(item.failures) for item in self.tenants) + len(self.orphan_failures)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["failure_count"] = self.failure_count
        return payload


def _positive_int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _retention_value(
    tenant: dict[str, Any],
    key: str,
    fallback: int,
) -> int:
    retention = tenant.get("retention")
    if not isinstance(retention, dict):
        return fallback
    return _positive_int(retention.get(key), fallback)


def _object_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _failure(operation: str, key: str, exc: Exception) -> dict[str, str]:
    return {
        "operation": operation,
        "object_key_sha256": _object_key_hash(key),
        "error_type": type(exc).__name__,
    }


def _tenant_from_object_key(key: str) -> str | None:
    parts = key.split("/", 3)
    if len(parts) >= 3 and parts[0] == "tenants" and parts[1]:
        return parts[1]
    return None


class MaintenanceService:
    """Apply tenant retention and reconcile unreferenced immutable objects."""

    def __init__(
        self,
        settings: Settings,
        repository: PhaseCRepository,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store

    def run_once(self, *, now: datetime | None = None) -> MaintenanceReport:
        current = as_utc(now or datetime.now(timezone.utc))
        report = MaintenanceReport(started_at=current.isoformat())
        tenants = self.repository.list_tenants(active_only=True)
        tenant_by_id = {str(item["tenant_id"]): item for item in tenants}

        for tenant in tenants:
            tenant_report = self._maintain_tenant(tenant, current)
            report.tenants.append(tenant_report)

        referenced = self.repository.referenced_object_keys()
        for item in self.object_store.list():
            if item.key in referenced:
                continue
            tenant = tenant_by_id.get(_tenant_from_object_key(item.key) or "")
            orphan_ttl = (
                _retention_value(
                    tenant,
                    "orphan_ttl_seconds",
                    self.settings.orphan_ttl_seconds,
                )
                if tenant is not None
                else self.settings.orphan_ttl_seconds
            )
            if current - as_utc(item.modified_at) < timedelta(seconds=orphan_ttl):
                continue
            try:
                self.object_store.delete(item.key)
                report.orphan_objects_deleted += 1
            except Exception as exc:  # noqa: BLE001 - retry on the next maintenance cycle
                report.orphan_failures.append(_failure("delete_orphan", item.key, exc))

        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report

    def _maintain_tenant(
        self,
        tenant: dict[str, Any],
        current: datetime,
    ) -> TenantMaintenanceReport:
        tenant_id = str(tenant["tenant_id"])
        report = TenantMaintenanceReport(tenant_id=tenant_id)

        upload_keys = self.repository.expire_unbound_uploads(tenant_id, now=current)
        report.expired_uploads = len(upload_keys)
        self._delete_objects(upload_keys, "delete_expired_upload", report)

        retained = self.repository.apply_retention(
            tenant_id,
            now=current,
            succeeded_days=_retention_value(
                tenant,
                "succeeded_days",
                self.settings.succeeded_retention_days,
            ),
            failed_days=_retention_value(
                tenant,
                "failed_days",
                self.settings.failed_retention_days,
            ),
            recovery_days=_retention_value(
                tenant,
                "recovery_days",
                self.settings.deletion_recovery_days,
            ),
        )
        report.hidden_jobs = len(retained["hidden"])
        for job_id in retained["purge_ready"]:
            try:
                object_keys = self.repository.purge_job_objects_metadata(
                    tenant_id,
                    job_id,
                    now=current,
                )
                report.purged_jobs += 1
                self._delete_objects(object_keys, "delete_purged_job_object", report)
            except Exception as exc:  # noqa: BLE001 - one job must not block tenant cleanup
                report.failures.append(
                    {
                        "operation": "purge_job",
                        "job_id_sha256": _object_key_hash(job_id),
                        "error_type": type(exc).__name__,
                    }
                )

        audit_days = _retention_value(
            tenant,
            "audit_days",
            self.settings.audit_retention_days,
        )
        cutoff = current - timedelta(days=audit_days)
        report.pruned_audit_rows = self.repository.prune_audit_before(
            tenant_id,
            before=cutoff,
        )
        report.pruned_cost_rows = self.repository.prune_cost_before(
            tenant_id,
            before=cutoff,
        )
        self.repository.audit(
            tenant_id,
            actor_id="system:maintenance",
            action="retention.cycle",
            resource_type="tenant",
            resource_id=tenant_id,
            result="partial" if report.failures else "succeeded",
            payload={
                "expired_uploads": report.expired_uploads,
                "hidden_jobs": report.hidden_jobs,
                "purged_jobs": report.purged_jobs,
                "deleted_objects": report.deleted_objects,
                "pruned_audit_rows": report.pruned_audit_rows,
                "pruned_cost_rows": report.pruned_cost_rows,
                "failure_count": len(report.failures),
            },
        )
        return report

    def _delete_objects(
        self,
        object_keys: list[str],
        operation: str,
        report: TenantMaintenanceReport,
    ) -> None:
        for key in object_keys:
            try:
                self.object_store.delete(key)
                report.deleted_objects += 1
            except Exception as exc:  # noqa: BLE001 - retry through orphan reconciliation
                report.failures.append(_failure(operation, key, exc))


def run_maintenance_worker(*, once: bool = False, interval_seconds: float | None = None) -> int:
    settings = load_settings()
    if settings.deployment_mode != "distributed":
        raise RuntimeError("maintenance worker requires CASE_VIDEO_DEPLOYMENT_MODE=distributed")
    database = Database.from_settings(settings)
    database.check_schema()
    service = MaintenanceService(
        settings,
        PhaseCRepository(database),
        object_store_from_settings(settings),
    )
    stop = StopSignal()
    stop.install()
    cycles = 0
    interval = float(interval_seconds or settings.maintenance_interval_seconds)
    try:
        while not stop.requested:
            report = service.run_once()
            cycles += 1
            LOGGER.info(
                "maintenance_cycle=%s",
                json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True),
            )
            if once:
                break
            deadline = time.monotonic() + max(1.0, interval)
            while not stop.requested and time.monotonic() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    finally:
        database.dispose()
    return cycles


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Run Phase C retention and orphan cleanup")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float)
    args = parser.parse_args()
    run_maintenance_worker(once=args.once, interval_seconds=args.interval)


if __name__ == "__main__":
    main()
