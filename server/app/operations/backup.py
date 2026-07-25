from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.engine import URL, make_url

from server.app.persistence.database import Database, SCHEMA_VERSION
from server.app.persistence.models import ArtifactBlob, JobInput, Upload
from server.app.persistence.object_store import (
    ObjectNotFound,
    ObjectStore,
    ObjectStoreError,
    sha256_file,
    validate_object_key,
)
from server.app.persistence.repository import PhaseCRepository
from server.app.services.streams import OutboxDispatcher, QueueRecoveryService, StreamsBroker


BACKUP_FORMAT_VERSION = 1
RPO_TARGET_SECONDS = 15 * 60
RTO_TARGET_SECONDS = 4 * 60 * 60


class BackupError(RuntimeError):
    pass


class BackupVerificationError(BackupError):
    pass


class RestoreConfirmationError(BackupError):
    pass


@dataclass(frozen=True)
class DatabaseSnapshot:
    backend: str
    filename: str
    size_bytes: int
    sha256: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_manifest(backup_dir: Path) -> dict[str, Any]:
    path = backup_dir / "backup-manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupVerificationError("backup manifest is missing or invalid") from exc
    if not isinstance(value, dict) or value.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupVerificationError("unsupported backup manifest format")
    return value


def _safe_backup_object_path(root: Path, key: str) -> Path:
    normalized = validate_object_key(key)
    path = (root / normalized).resolve()
    root = root.resolve()
    if root not in path.parents:
        raise BackupVerificationError("backup object path escapes its root")
    return path


def _copy_object_to_backup(store: ObjectStore, metadata: Any, root: Path) -> dict[str, Any]:
    key = validate_object_key(str(metadata.key))
    target = _safe_backup_object_path(root, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with store.open(key) as source, tempfile.NamedTemporaryFile(
        "wb", dir=str(target.parent), delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    actual_sha = digest.hexdigest()
    if size != int(metadata.size_bytes) or actual_sha != str(metadata.sha256):
        temporary.unlink(missing_ok=True)
        raise BackupVerificationError(f"object changed while it was backed up: {key}")
    os.replace(temporary, target)
    return {
        "key": key,
        "size_bytes": size,
        "sha256": actual_sha,
        "media_type": str(metadata.media_type),
        "modified_at": metadata.modified_at.isoformat(),
    }


def _postgres_environment(url: URL) -> dict[str, str]:
    environment = dict(os.environ)
    if url.password:
        environment["PGPASSWORD"] = url.password
    sslmode = url.query.get("sslmode")
    if sslmode:
        environment["PGSSLMODE"] = str(sslmode)
    return environment


def _postgres_connection_args(url: URL) -> list[str]:
    args: list[str] = []
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", url.username])
    if url.database:
        args.extend(["--dbname", url.database])
    return args


def _run_checked(command: list[str], *, environment: dict[str, str], timeout_seconds: int) -> None:
    try:
        result = subprocess.run(
            command,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise BackupError(f"required database utility is not installed: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"database utility timed out: {command[0]}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "database utility failed").strip()
        raise BackupError(f"{command[0]} failed: {detail[:2000]}")


def _snapshot_database(database_url: str | URL, destination: Path) -> DatabaseSnapshot:
    url = make_url(database_url)
    backend = url.get_backend_name()
    if backend == "sqlite":
        if not url.database or url.database == ":memory:":
            raise BackupError("SQLite backups require a file-backed database")
        filename = "database.sqlite3"
        output = destination / filename
        source_path = Path(url.database).resolve()
        if not source_path.is_file():
            raise BackupError("SQLite database file does not exist")
        with sqlite3.connect(source_path) as source, sqlite3.connect(output) as target:
            source.backup(target)
    elif backend == "postgresql":
        filename = "database.pgdump"
        output = destination / filename
        _run_checked(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(output),
                *_postgres_connection_args(url),
            ],
            environment=_postgres_environment(url),
            timeout_seconds=60 * 60,
        )
    else:
        raise BackupError(f"unsupported database backend: {backend}")
    return DatabaseSnapshot(
        backend=backend,
        filename=filename,
        size_bytes=output.stat().st_size,
        sha256=sha256_file(output),
    )


class BackupService:
    def __init__(self, database: Database, object_store: ObjectStore) -> None:
        self.database = database
        self.object_store = object_store

    def create(self, destination: Path, *, backup_id: str | None = None) -> dict[str, Any]:
        started_at = utc_now()
        schema_version = self.database.check_schema()
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise BackupError("backup destination already exists")
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.partial-", dir=str(destination.parent))
        )
        try:
            database_snapshot = _snapshot_database(self.database.engine.url, temporary)
            recovery_point_at = utc_now()
            object_root = temporary / "objects"
            object_entries = [
                _copy_object_to_backup(self.object_store, metadata, object_root)
                for metadata in sorted(self.object_store.list(), key=lambda item: item.key)
            ]
            completed_at = utc_now()
            manifest: dict[str, Any] = {
                "format_version": BACKUP_FORMAT_VERSION,
                "backup_id": backup_id or destination.name,
                "started_at": started_at.isoformat(),
                "recovery_point_at": recovery_point_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "schema_version": schema_version,
                "database": {
                    "backend": database_snapshot.backend,
                    "filename": database_snapshot.filename,
                    "size_bytes": database_snapshot.size_bytes,
                    "sha256": database_snapshot.sha256,
                },
                "objects": object_entries,
                "summary": {
                    "object_count": len(object_entries),
                    "object_bytes": sum(int(item["size_bytes"]) for item in object_entries),
                    "elapsed_seconds": round((completed_at - started_at).total_seconds(), 6),
                },
            }
            _write_json(temporary / "backup-manifest.json", manifest)
            verify_backup(temporary)
            temporary.rename(destination)
            return manifest
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = backup_dir.resolve()
    manifest = _read_manifest(backup_dir)
    database = manifest.get("database")
    if not isinstance(database, dict):
        raise BackupVerificationError("backup database entry is invalid")
    database_path = backup_dir / str(database.get("filename", ""))
    if not database_path.is_file():
        raise BackupVerificationError("database snapshot is missing")
    if database_path.stat().st_size != int(database.get("size_bytes", -1)):
        raise BackupVerificationError("database snapshot size mismatch")
    if sha256_file(database_path) != database.get("sha256"):
        raise BackupVerificationError("database snapshot hash mismatch")

    objects = manifest.get("objects")
    if not isinstance(objects, list):
        raise BackupVerificationError("backup object inventory is invalid")
    seen: set[str] = set()
    for item in objects:
        if not isinstance(item, dict):
            raise BackupVerificationError("backup object inventory entry is invalid")
        key = validate_object_key(str(item.get("key", "")))
        if key in seen:
            raise BackupVerificationError(f"duplicate backup object key: {key}")
        seen.add(key)
        path = _safe_backup_object_path(backup_dir / "objects", key)
        if not path.is_file():
            raise BackupVerificationError(f"backup object is missing: {key}")
        if path.stat().st_size != int(item.get("size_bytes", -1)):
            raise BackupVerificationError(f"backup object size mismatch: {key}")
        if sha256_file(path) != item.get("sha256"):
            raise BackupVerificationError(f"backup object hash mismatch: {key}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BackupVerificationError("backup schema version is unsupported by this release")
    return manifest


def _restore_database(snapshot: Path, manifest: dict[str, Any], target_database_url: str) -> None:
    database = manifest["database"]
    target_url = make_url(target_database_url)
    backend = target_url.get_backend_name()
    if backend != database.get("backend"):
        raise BackupError("backup and restore database backends differ")
    if backend == "sqlite":
        if not target_url.database or target_url.database == ":memory:":
            raise BackupError("SQLite restore requires a file-backed target database")
        target_path = Path(target_url.database).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.stat().st_size > 0:
            raise BackupError("SQLite restore target must not already contain a database")
        with sqlite3.connect(snapshot) as source, sqlite3.connect(target_path) as target:
            source.backup(target)
    elif backend == "postgresql":
        _run_checked(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                *_postgres_connection_args(target_url),
                str(snapshot),
            ],
            environment=_postgres_environment(target_url),
            timeout_seconds=4 * 60 * 60,
        )
    else:
        raise BackupError(f"unsupported database backend: {backend}")


def _restore_objects(
    backup_dir: Path,
    entries: Iterable[dict[str, Any]],
    target_store: ObjectStore,
) -> int:
    restored = 0
    for item in entries:
        key = validate_object_key(str(item["key"]))
        source = _safe_backup_object_path(backup_dir / "objects", key)
        try:
            current = target_store.head(key)
        except ObjectNotFound:
            current = None
        if current is not None:
            if current.sha256 != item["sha256"] or current.size_bytes != int(item["size_bytes"]):
                raise BackupVerificationError(f"restore target contains conflicting object: {key}")
            continue
        restored_metadata = target_store.put_file(
            key,
            source,
            media_type=str(item.get("media_type") or "application/octet-stream"),
        )
        if (
            restored_metadata.sha256 != item["sha256"]
            or restored_metadata.size_bytes != int(item["size_bytes"])
        ):
            raise BackupVerificationError(f"restored object failed verification: {key}")
        restored += 1
    return restored


def verify_database_object_references(database: Database, object_store: ObjectStore) -> dict[str, Any]:
    references: dict[str, dict[str, Any]] = {}
    with database.session() as session:
        for blob in session.scalars(select(ArtifactBlob)):
            references[blob.object_key] = {
                "kind": "artifact_blob",
                "size_bytes": blob.size_bytes,
                "sha256": blob.sha256,
            }
        for upload in session.scalars(select(Upload).where(Upload.object_key.is_not(None))):
            references[str(upload.object_key)] = {
                "kind": "upload",
                "size_bytes": upload.size_bytes,
                "sha256": upload.sha256,
            }
        for job_input in session.scalars(select(JobInput).where(JobInput.object_key.is_not(None))):
            references[str(job_input.object_key)] = {
                "kind": "job_input",
                "size_bytes": job_input.size_bytes,
                "sha256": job_input.sha256,
            }

    errors: list[dict[str, Any]] = []
    for key, expected in sorted(references.items()):
        try:
            actual = object_store.head(key)
        except (ObjectNotFound, ObjectStoreError) as exc:
            errors.append({"key": key, "kind": expected["kind"], "error": type(exc).__name__})
            continue
        if expected["size_bytes"] is not None and actual.size_bytes != int(expected["size_bytes"]):
            errors.append({"key": key, "kind": expected["kind"], "error": "size_mismatch"})
        if expected["sha256"] is not None and actual.sha256 != str(expected["sha256"]):
            errors.append({"key": key, "kind": expected["kind"], "error": "hash_mismatch"})
    return {
        "reference_count": len(references),
        "verified_count": len(references) - len({item["key"] for item in errors}),
        "errors": errors,
    }


class RestoreService:
    def __init__(
        self,
        *,
        target_database_url: str,
        target_store: ObjectStore,
        broker: StreamsBroker,
        max_attempts: int,
    ) -> None:
        self.target_database_url = target_database_url
        self.target_store = target_store
        self.broker = broker
        self.max_attempts = max_attempts

    def restore(self, backup_dir: Path, *, confirmation: str) -> dict[str, Any]:
        started_at = utc_now()
        manifest = verify_backup(backup_dir)
        expected_confirmation = f"RESTORE {manifest['backup_id']}"
        if confirmation != expected_confirmation:
            raise RestoreConfirmationError(f"restore requires exact confirmation: {expected_confirmation}")
        snapshot = backup_dir.resolve() / str(manifest["database"]["filename"])
        _restore_database(snapshot, manifest, self.target_database_url)
        restored_objects = _restore_objects(
            backup_dir.resolve(),
            manifest["objects"],
            self.target_store,
        )

        database = Database(self.target_database_url)
        try:
            schema_version = database.check_schema()
            references = verify_database_object_references(database, self.target_store)
            if references["errors"]:
                raise BackupVerificationError("restored database contains invalid object references")
            repository = PhaseCRepository(database)
            dispatcher = OutboxDispatcher(repository, self.broker)
            recovery = QueueRecoveryService(
                repository,
                dispatcher,
                max_attempts=self.max_attempts,
            )
            queue_report = recovery.recover_after_restore()
        finally:
            database.dispose()

        completed_at = utc_now()
        elapsed = (completed_at - started_at).total_seconds()
        recovery_point = datetime.fromisoformat(str(manifest["recovery_point_at"]))
        if recovery_point.tzinfo is None:
            recovery_point = recovery_point.replace(tzinfo=timezone.utc)
        recovery_point_age = max(0.0, (started_at - recovery_point).total_seconds())
        return {
            "backup_id": manifest["backup_id"],
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "schema_version": schema_version,
            "restored_objects": restored_objects,
            "object_references": references,
            "queue_recovery": queue_report,
            "measured_rpo_seconds": round(recovery_point_age, 6),
            "measured_rto_seconds": round(elapsed, 6),
            "rpo_target_seconds": RPO_TARGET_SECONDS,
            "rto_target_seconds": RTO_TARGET_SECONDS,
            "rpo_pass": recovery_point_age <= RPO_TARGET_SECONDS,
            "rto_pass": elapsed <= RTO_TARGET_SECONDS,
        }
