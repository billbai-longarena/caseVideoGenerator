from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

from server.app.persistence.database import Database, SCHEMA_VERSION
from server.app.persistence.models import Job, JobStageRun, ModelRun
from server.app.persistence.repository import TERMINAL_JOB_STATUSES, canonical_json


UPGRADE_SNAPSHOT_FORMAT_VERSION = 1
_SENSITIVE_KEY_PARTS = ("credential", "password", "secret", "token", "api_key")


class UpgradeSnapshotError(RuntimeError):
    pass


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return copy.deepcopy(value)


def _record_digest(record: dict[str, Any]) -> str:
    return _sha256_json({key: value for key, value in record.items() if key != "sha256"})


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    return _sha256_json(
        {
            "format_version": snapshot.get("format_version"),
            "jobs": snapshot.get("jobs"),
        }
    )


def _changed_paths(expected: Any, actual: Any, *, prefix: str = "$") -> list[str]:
    if type(expected) is not type(actual):
        return [prefix]
    if isinstance(expected, dict):
        paths: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{prefix}.{key}"
            if key not in expected or key not in actual:
                paths.append(child)
            else:
                paths.extend(_changed_paths(expected[key], actual[key], prefix=child))
        return paths
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [prefix]
        paths = []
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            paths.extend(
                _changed_paths(expected_item, actual_item, prefix=f"{prefix}[{index}]")
            )
        return paths
    return [] if expected == actual else [prefix]


def _job_key(tenant_id: str, job_id: str) -> str:
    return f"{tenant_id}/{job_id}"


class UpgradeSnapshotService:
    """Capture and verify immutable pins for in-flight Phase C jobs.

    Runtime status, progress, timestamps, and newly created stage/model rows are
    intentionally not frozen. Existing immutable records must remain byte-for-
    byte equivalent, while model rows created after the baseline must still
    conform to the job's captured task registry.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def capture(self) -> dict[str, Any]:
        schema_version = self.database.check_schema()
        with self.database.session() as session:
            jobs = list(
                session.scalars(
                    select(Job)
                    .where(
                        Job.status.not_in(TERMINAL_JOB_STATUSES),
                        Job.deleted_at.is_(None),
                    )
                    .order_by(Job.tenant_id, Job.id)
                )
            )
            records = [self._job_record(session, job) for job in jobs]
        snapshot: dict[str, Any] = {
            "format_version": UPGRADE_SNAPSHOT_FORMAT_VERSION,
            "captured_at": _utc_iso(),
            "schema_version": schema_version,
            "jobs": records,
            "summary": {
                "in_flight_jobs": len(records),
                "stage_runs": sum(len(item["stage_runs"]) for item in records),
                "model_runs": sum(len(item["model_runs"]) for item in records),
            },
        }
        snapshot["sha256"] = _snapshot_digest(snapshot)
        return snapshot

    def verify(self, baseline: dict[str, Any]) -> dict[str, Any]:
        self._validate_baseline(baseline)
        issues: list[dict[str, Any]] = []
        baseline_jobs = {
            str(item["job_key"]): item
            for item in baseline.get("jobs", [])
            if isinstance(item, dict) and item.get("job_key")
        }
        with self.database.session() as session:
            for key, expected in sorted(baseline_jobs.items()):
                tenant_id = str(expected.get("tenant_id", ""))
                job_id = str(expected.get("job_id", ""))
                job = session.get(Job, (tenant_id, job_id))
                if job is None:
                    issues.append(
                        {
                            "job_key": key,
                            "scope": "job",
                            "code": "job_missing",
                            "paths": ["$"],
                        }
                    )
                    continue
                actual = self._job_record(session, job)
                self._compare_record(
                    issues,
                    key,
                    "job_snapshot",
                    expected["job_snapshot"],
                    actual["job_snapshot"],
                )
                self._compare_indexed_records(
                    issues,
                    key,
                    "stage_run",
                    expected.get("stage_runs", []),
                    actual.get("stage_runs", []),
                    id_field="stage_run_id",
                )
                self._compare_indexed_records(
                    issues,
                    key,
                    "model_run",
                    expected.get("model_runs", []),
                    actual.get("model_runs", []),
                    id_field="model_run_id",
                )
                issues.extend(self._model_registry_issues(key, actual))
        report = {
            "acceptance_id": "C-UPGRADE-01",
            "verified_at": _utc_iso(),
            "baseline_sha256": baseline["sha256"],
            "baseline_schema_version": baseline.get("schema_version"),
            "current_schema_version": self.database.check_schema(),
            "jobs_checked": len(baseline_jobs),
            "issues": issues,
            "passed": not issues,
        }
        report["sha256"] = _sha256_json(report)
        return report

    def _job_record(self, session: Any, job: Job) -> dict[str, Any]:
        stage_runs = list(
            session.scalars(
                select(JobStageRun)
                .where(
                    JobStageRun.tenant_id == job.tenant_id,
                    JobStageRun.job_id == job.id,
                )
                .order_by(JobStageRun.id)
            )
        )
        model_runs = list(
            session.scalars(
                select(ModelRun)
                .where(ModelRun.tenant_id == job.tenant_id, ModelRun.job_id == job.id)
                .order_by(ModelRun.id)
            )
        )
        manifest = job.manifest if isinstance(job.manifest, dict) else {}
        job_snapshot = {
            "route_snapshot": _redact(job.route_snapshot),
            "config_snapshot": _redact(job.config_snapshot),
            "engine_snapshot": _redact(job.engine_snapshot),
            "manifest_pins": _redact(
                {
                    "manifest_version": manifest.get("manifest_version"),
                    "model_routes": manifest.get("model_routes", {}),
                    "prompt_pins": manifest.get("prompt_pins", {}),
                    "contract_versions": manifest.get("contract_versions", {}),
                    "task_registry": manifest.get("task_registry", {}),
                }
            ),
        }
        job_snapshot["sha256"] = _record_digest(job_snapshot)
        stage_records = [
            {
                "stage_run_id": run.id,
                "stage": run.stage,
                "attempt": run.attempt,
                "input_hash": run.input_hash,
                "route_snapshot_hash": run.route_snapshot_hash,
                "config_snapshot_hash": run.config_snapshot_hash,
            }
            for run in stage_runs
        ]
        for record in stage_records:
            record["sha256"] = _record_digest(record)
        model_records = [
            {
                "model_run_id": run.id,
                "stage_run_id": run.stage_run_id,
                "task": run.task,
                "provider": run.provider,
                "model": run.model,
                "route_snapshot": _redact(run.route_snapshot),
                "prompt_version": run.prompt_version,
                "schema_version": run.schema_version,
            }
            for run in model_runs
        ]
        for record in model_records:
            record["sha256"] = _record_digest(record)
        record = {
            "job_key": _job_key(job.tenant_id, job.id),
            "tenant_id": job.tenant_id,
            "job_id": job.id,
            "job_snapshot": job_snapshot,
            "stage_runs": stage_records,
            "model_runs": model_records,
        }
        record["sha256"] = _record_digest(record)
        return record

    @staticmethod
    def _compare_record(
        issues: list[dict[str, Any]],
        job_key: str,
        scope: str,
        expected: dict[str, Any],
        actual: dict[str, Any],
        *,
        record_id: str | None = None,
    ) -> None:
        if expected == actual:
            return
        issue: dict[str, Any] = {
            "job_key": job_key,
            "scope": scope,
            "code": "immutable_snapshot_changed",
            "paths": _changed_paths(expected, actual),
            "expected_sha256": _record_digest(expected),
            "actual_sha256": _record_digest(actual),
        }
        if record_id is not None:
            issue["record_id"] = record_id
        issues.append(issue)

    @classmethod
    def _compare_indexed_records(
        cls,
        issues: list[dict[str, Any]],
        job_key: str,
        scope: str,
        expected_records: Iterable[dict[str, Any]],
        actual_records: Iterable[dict[str, Any]],
        *,
        id_field: str,
    ) -> None:
        actual_by_id = {str(item[id_field]): item for item in actual_records}
        for expected in expected_records:
            record_id = str(expected[id_field])
            actual = actual_by_id.get(record_id)
            if actual is None:
                issues.append(
                    {
                        "job_key": job_key,
                        "scope": scope,
                        "record_id": record_id,
                        "code": "immutable_record_missing",
                        "paths": ["$"],
                    }
                )
                continue
            cls._compare_record(
                issues,
                job_key,
                scope,
                expected,
                actual,
                record_id=record_id,
            )

    @staticmethod
    def _model_registry_issues(job_key: str, record: dict[str, Any]) -> list[dict[str, Any]]:
        registry = record["job_snapshot"]["manifest_pins"].get("task_registry", {})
        issues: list[dict[str, Any]] = []
        for model_run in record.get("model_runs", []):
            task = str(model_run.get("task", ""))
            task_pin = registry.get(task) if isinstance(registry, dict) else None
            if not isinstance(task_pin, dict):
                issues.append(
                    {
                        "job_key": job_key,
                        "scope": "model_run",
                        "record_id": model_run.get("model_run_id"),
                        "code": "task_not_in_registry_snapshot",
                        "paths": ["$.task"],
                    }
                )
                continue
            expected = {
                "provider": task_pin.get("provider"),
                "model": task_pin.get("model"),
                "prompt_version": task_pin.get("prompt_version"),
                "schema_version": (
                    task_pin.get("output_schema", {}).get("version")
                    if isinstance(task_pin.get("output_schema"), dict)
                    else None
                ),
            }
            actual = {key: model_run.get(key) for key in expected}
            paths = _changed_paths(expected, actual)
            route = model_run.get("route_snapshot", {})
            if isinstance(route, dict):
                for field in ("provider", "model"):
                    if route.get(field) is not None and route.get(field) != expected[field]:
                        paths.append(f"$.route_snapshot.{field}")
            if paths:
                issues.append(
                    {
                        "job_key": job_key,
                        "scope": "model_run",
                        "record_id": model_run.get("model_run_id"),
                        "code": "model_run_not_pinned_to_job_registry",
                        "paths": sorted(set(paths)),
                        "expected_sha256": _sha256_json(expected),
                        "actual_sha256": _sha256_json(actual),
                    }
                )
        return issues

    @staticmethod
    def _validate_baseline(baseline: dict[str, Any]) -> None:
        if baseline.get("format_version") != UPGRADE_SNAPSHOT_FORMAT_VERSION:
            raise UpgradeSnapshotError("unsupported upgrade snapshot format")
        if not isinstance(baseline.get("jobs"), list):
            raise UpgradeSnapshotError("upgrade snapshot jobs inventory is invalid")
        if baseline.get("sha256") != _snapshot_digest(baseline):
            raise UpgradeSnapshotError("upgrade snapshot digest mismatch")
        seen: set[str] = set()
        for record in baseline["jobs"]:
            if not isinstance(record, dict) or not record.get("job_key"):
                raise UpgradeSnapshotError("upgrade snapshot contains an invalid job record")
            key = str(record["job_key"])
            if key in seen:
                raise UpgradeSnapshotError(f"duplicate job record in upgrade snapshot: {key}")
            seen.add(key)
            if record.get("sha256") != _record_digest(record):
                raise UpgradeSnapshotError(f"upgrade job snapshot digest mismatch: {key}")


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_snapshot(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeSnapshotError("upgrade snapshot is missing or invalid") from exc
    if not isinstance(value, dict):
        raise UpgradeSnapshotError("upgrade snapshot root must be an object")
    return value


__all__ = [
    "UpgradeSnapshotError",
    "UpgradeSnapshotService",
    "read_snapshot",
    "write_snapshot",
]
