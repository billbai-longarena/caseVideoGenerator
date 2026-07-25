from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

import fcntl

from server.app.core.config import Settings
from server.app.core.errors import AppError
from server.app.models.job import ApprovalMode, InputMode, JobStatus, utc_now_iso
from server.app.services.manifest_factory import build_job_manifest
from server.app.services.task_registry import TaskRegistry


SAFE_DOWNLOAD_NAME = re.compile(r"[^A-Za-z0-9._-]+")
ARTIFACT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".log",
    ".wav",
    ".mp3",
    ".mp4",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}
SECRET_NAMES = {".env", ".env.local", ".env.production"}
REQUIRED_PHASE_A_FILES = ("title.txt", "narration.txt")


class StorageError(ValueError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, tempfile.NamedTemporaryFile(
        "wb",
        dir=str(destination.parent),
        delete=False,
    ) as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())
        temp_name = output_handle.name
    os.replace(temp_name, destination)
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


@contextmanager
def exclusive_file_lock(path: Path) -> Iterable[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def safe_download_filename(value: str) -> str:
    cleaned = SAFE_DOWNLOAD_NAME.sub("-", value.strip()).strip(".-")
    return cleaned or "artifact"


def assert_inside(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise StorageError(f"path escapes allowed root: {path}")
    return resolved


def assert_no_symlinks(root: Path) -> None:
    for item in root.rglob("*"):
        if item.is_symlink():
            raise StorageError(f"symbolic links are not allowed in seed projects: {item}")


def copy_project_tree(source: Path, destination: Path) -> None:
    assert_no_symlinks(source)
    if destination.exists():
        shutil.rmtree(destination)
    ignore = shutil.ignore_patterns(
        ".env",
        ".env.*",
        "__pycache__",
        ".DS_Store",
        "node_modules",
        ".case-video.lock",
    )
    shutil.copytree(source, destination, ignore=ignore)


class JobStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.task_registry = TaskRegistry(settings)
        self.contracts = self.task_registry.contracts
        self.root = settings.data_root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "_idempotency").mkdir(parents=True, exist_ok=True)

    def create_job(
        self,
        project_name: str,
        approval_mode: ApprovalMode,
        idempotency_key: str | None,
        target_duration: str | None = None,
        seed_project: str | None = None,
        *,
        input_mode: InputMode | str = InputMode.project,
        target_duration_seconds: dict[str, int] | None = None,
        program: str = "销售不复杂",
        upload_ids: list[str] | None = None,
        structured_input: dict[str, Any] | None = None,
        budget_limit_micros: int | None = None,
        request_hash: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.find_idempotent_job(idempotency_key, request_hash=request_hash)
            if existing:
                return existing

        mode = input_mode.value if isinstance(input_mode, InputMode) else str(input_mode)
        job_id = f"job_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        job_root = self.job_root(job_id)
        project_root = job_root / "project"
        manifest = build_job_manifest(
            self.settings,
            project_name=project_name,
            approval_mode=approval_mode,
            input_mode=mode,
            idempotency_key=idempotency_key,
            target_duration=target_duration,
            target_duration_seconds=target_duration_seconds,
            program=program,
            seed_project=seed_project,
            upload_ids=upload_ids,
            structured_input=structured_input,
            budget_limit_micros=budget_limit_micros,
            job_id=job_id,
            task_registry=self.task_registry,
        )
        (job_root / "source").mkdir(parents=True, exist_ok=True)
        (job_root / "logs").mkdir(parents=True, exist_ok=True)
        (job_root / "revisions" / "case-model").mkdir(parents=True, exist_ok=True)
        (job_root / "revisions" / "editorial").mkdir(parents=True, exist_ok=True)
        (job_root / "revisions" / "visual-plan").mkdir(parents=True, exist_ok=True)
        (job_root / "stage-runs").mkdir(parents=True, exist_ok=True)
        project_root.mkdir(parents=True, exist_ok=True)

        if structured_input is not None:
            atomic_write_json(job_root / "source" / "structured_input.json", structured_input)

        if seed_project:
            source = assert_inside(self.settings.seed_projects_root / seed_project, self.settings.seed_projects_root)
            if not source.is_dir():
                raise StorageError(f"seed project not found: {seed_project}")
            copy_project_tree(source, project_root)
            self.validate_phase_a_project(project_root)

        self.write_manifest(job_id, manifest)
        self.append_event(job_id, "job.created", "created", "任务已创建", {"dry_run": self.settings.dry_run})

        if idempotency_key:
            self.store_idempotency(idempotency_key, job_id, request_hash=request_hash)
        return manifest

    def extract_project_zip(self, job_id: str, zip_path: Path) -> None:
        project_root = self.project_root(job_id)
        if project_root.exists():
            shutil.rmtree(project_root)
        project_root.mkdir(parents=True, exist_ok=True)
        total_size = 0
        total_compressed = 0
        file_count = 0
        seen: set[str] = set()
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                parts = [part for part in normalized.split("/") if part]
                if not parts or normalized.startswith("/") or "\x00" in normalized or ".." in parts:
                    raise StorageError(f"archive path escapes allowed root: {info.filename}")
                if normalized in seen:
                    raise StorageError(f"duplicate archive path: {info.filename}")
                seen.add(normalized)
                if not info.is_dir():
                    file_count += 1
                    if file_count > self.settings.max_archive_files:
                        raise StorageError("uploaded archive contains too many files")
                total_size += info.file_size
                total_compressed += info.compress_size
                if total_size > self.settings.max_archive_expansion_bytes:
                    raise StorageError("uploaded archive exceeds max expanded size")
                if info.file_size and info.compress_size == 0:
                    raise StorageError(f"suspicious zero-size compressed entry: {info.filename}")
                if info.compress_size and info.file_size / info.compress_size > self.settings.max_archive_compression_ratio:
                    raise StorageError(f"archive entry compression ratio is too high: {info.filename}")
                target = assert_inside(project_root / normalized, project_root)
                mode = (info.external_attr >> 16) & 0o170000
                if mode and mode not in {stat.S_IFREG, stat.S_IFDIR}:
                    raise StorageError(f"special files are not allowed in archives: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as dest:
                    copied = 0
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > info.file_size or total_size - info.file_size + copied > self.settings.max_archive_expansion_bytes:
                            raise StorageError("archive expanded beyond its declared limit")
                        dest.write(chunk)
            if total_compressed and total_size / total_compressed > self.settings.max_archive_compression_ratio:
                raise StorageError("archive compression ratio is too high")
        self.validate_phase_a_project(project_root)
        self.append_event(job_id, "source.uploaded", "source_ready", "项目压缩包已导入", {})

    def validate_phase_a_project(self, project_root: Path) -> None:
        missing = [name for name in REQUIRED_PHASE_A_FILES if not (project_root / name).is_file()]
        if missing:
            raise StorageError(f"phase A project is missing required files: {', '.join(missing)}")
        has_storyboard = (project_root / "storyboard_plan.json").is_file() or (
            project_root / "rich_storyboard.json"
        ).is_file()
        if not has_storyboard:
            raise StorageError("phase A project requires storyboard_plan.json or rich_storyboard.json")

    def job_root(self, job_id: str) -> Path:
        return assert_inside(self.root / job_id, self.root)

    def project_root(self, job_id: str) -> Path:
        return self.job_root(job_id) / "project"

    def manifest_path(self, job_id: str) -> Path:
        return self.job_root(job_id) / "job_manifest.json"

    def events_path(self, job_id: str) -> Path:
        return self.job_root(job_id) / "events.jsonl"

    def model_runs_path(self, job_id: str) -> Path:
        return self.job_root(job_id) / "model_runs.jsonl"

    def model_cache_path(self, job_id: str, idempotency_key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", idempotency_key):
            raise StorageError("invalid model cache key")
        return self.job_root(job_id) / "model-cache" / f"{idempotency_key}.json"

    def pipeline_log_path(self, job_id: str) -> Path:
        return self.job_root(job_id) / "logs" / "pipeline.log"

    def read_manifest(self, job_id: str) -> dict[str, Any]:
        path = self.manifest_path(job_id)
        if not path.is_file():
            raise StorageError(f"job not found: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_manifests(
        self,
        status: str | None = None,
        q: str | None = None,
        needs_action: bool | None = None,
        approval_mode: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        needle = q.strip().lower() if q else None
        for path in self.root.glob("job_*/job_manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status and manifest.get("status") != status:
                continue
            if needs_action is not None and bool(manifest.get("needs_action")) != needs_action:
                continue
            if approval_mode and manifest.get("approval_mode") != approval_mode:
                continue
            created_at = manifest.get("created_at", "")
            if created_from and created_at < created_from:
                continue
            if created_to and created_at > created_to:
                continue
            if needle:
                haystack = f"{manifest.get('project_name', '')} {manifest.get('job_id', '')}".lower()
                if needle not in haystack:
                    continue
            manifests.append(manifest)
        manifests.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return manifests

    def write_manifest(self, job_id: str, manifest: dict[str, Any]) -> None:
        with exclusive_file_lock(self.job_root(job_id) / ".manifest.lock"):
            manifest["updated_at"] = utc_now_iso()
            self.contracts.validate("job_manifest", "v2", manifest)
            atomic_write_json(self.manifest_path(job_id), manifest)

    def mutate_manifest(
        self,
        job_id: str,
        mutation: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        with exclusive_file_lock(self.job_root(job_id) / ".manifest.lock"):
            manifest = self.read_manifest(job_id)
            mutation(manifest)
            manifest["updated_at"] = utc_now_iso()
            self.contracts.validate("job_manifest", "v2", manifest)
            atomic_write_json(self.manifest_path(job_id), manifest)
            return manifest

    def update_manifest(self, job_id: str, **updates: Any) -> dict[str, Any]:
        return self.mutate_manifest(job_id, lambda manifest: manifest.update(updates))

    def append_event(
        self,
        job_id: str,
        event_type: str,
        stage: str | None,
        message: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        path = self.events_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.job_root(job_id) / ".events.lock"):
            seq = 1
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    seq += sum(1 for line in handle if line.strip())
            record = {
                "seq": seq,
                "event_id": seq,
                "job_id": job_id,
                "timestamp": utc_now_iso(),
                "occurred_at": utc_now_iso(),
                "type": event_type,
                "stage": stage,
                "message": message,
                "data": data or {},
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return record

    def read_events(self, job_id: str, after: int = 0) -> list[dict[str, Any]]:
        path = self.events_path(job_id)
        if not path.exists():
            return []
        events = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["seq"] > after:
                    events.append(event)
        return events

    def append_model_run(self, job_id: str, record: dict[str, Any]) -> None:
        path = self.model_runs_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(self.job_root(job_id) / ".model-runs.lock"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    @contextmanager
    def model_cache_guard(self, job_id: str, idempotency_key: str) -> Iterator[None]:
        cache_path = self.model_cache_path(job_id, idempotency_key)
        with exclusive_file_lock(cache_path.with_suffix(".lock")):
            yield

    def read_model_cache(self, job_id: str, idempotency_key: str) -> dict[str, Any] | None:
        path = self.model_cache_path(job_id, idempotency_key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError("model cache record is corrupt") from exc
        if not isinstance(payload, dict):
            raise StorageError("model cache record must be an object")
        return payload

    def write_model_cache(
        self,
        job_id: str,
        idempotency_key: str,
        record: dict[str, Any],
    ) -> None:
        atomic_write_json(self.model_cache_path(job_id, idempotency_key), record)

    def store_idempotency(self, idempotency_key: str, job_id: str, request_hash: str | None = None) -> None:
        key_path = self.root / "_idempotency" / f"{sha256_text(idempotency_key)}.json"
        with exclusive_file_lock(key_path.with_suffix(".lock")):
            if key_path.is_file():
                existing = json.loads(key_path.read_text(encoding="utf-8"))
                if existing.get("job_id") != job_id or (
                    request_hash is not None and existing.get("request_hash") not in {None, request_hash}
                ):
                    raise AppError("idempotency_conflict", "idempotency key is already bound to another request")
                return
            atomic_write_json(
                key_path,
                {"job_id": job_id, "request_hash": request_hash, "created_at": utc_now_iso()},
            )

    def find_idempotent_job(
        self,
        idempotency_key: str,
        request_hash: str | None = None,
    ) -> dict[str, Any] | None:
        key_path = self.root / "_idempotency" / f"{sha256_text(idempotency_key)}.json"
        if not key_path.is_file():
            return None
        record = json.loads(key_path.read_text(encoding="utf-8"))
        stored_hash = record.get("request_hash")
        if request_hash is not None and stored_hash is not None and request_hash != stored_hash:
            raise AppError("idempotency_conflict", "idempotency key was reused with a different request body")
        job_id = record["job_id"]
        return self.read_manifest(job_id)

    def set_queued(self, job_id: str) -> dict[str, Any]:
        manifest = self.read_manifest(job_id)
        if manifest["status"] in {JobStatus.succeeded.value, JobStatus.canceled.value}:
            return manifest
        manifest.update(
            {
                "status": JobStatus.queued.value,
                "display_status": "排队中",
                "can_cancel": True,
                "can_retry": False,
                "needs_action": False,
                "next_action": None,
            }
        )
        self.write_manifest(job_id, manifest)
        self.append_event(job_id, "job.queued", manifest["stage"], "任务已入队", {})
        return manifest

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        manifest = self.read_manifest(job_id)
        if manifest["status"] in {JobStatus.succeeded.value, JobStatus.failed.value, JobStatus.canceled.value}:
            return manifest
        manifest.update(
            {
                "cancel_requested": True,
                "status": JobStatus.canceling.value,
                "display_status": "正在取消",
                "can_cancel": False,
            }
        )
        self.write_manifest(job_id, manifest)
        self.append_event(job_id, "job.cancel_requested", manifest["stage"], "已请求取消任务", {})
        return manifest

    def mark_canceled(self, job_id: str, stage: str) -> dict[str, Any]:
        manifest = self.read_manifest(job_id)
        manifest.update(
            {
                "status": JobStatus.canceled.value,
                "display_status": "已取消",
                "stage": stage,
                "needs_action": False,
                "next_action": None,
                "can_cancel": False,
                "can_retry": True,
                "last_heartbeat_at": utc_now_iso(),
            }
        )
        self.write_manifest(job_id, manifest)
        self.append_event(job_id, "job.canceled", stage, "任务已取消", {})
        return manifest

    def mark_failed(self, job_id: str, stage: str, error_code: str, message: str) -> dict[str, Any]:
        manifest = self.read_manifest(job_id)
        manifest.update(
            {
                "status": JobStatus.failed.value,
                "display_status": "失败",
                "stage": stage,
                "needs_action": True,
                "next_action": "查看失败并重试",
                "can_cancel": False,
                "can_retry": True,
                "last_heartbeat_at": utc_now_iso(),
                "error": {
                    "error_id": f"err_{uuid.uuid4().hex[:16]}",
                    "stage": stage,
                    "code": error_code,
                    "message": message,
                },
            }
        )
        self.write_manifest(job_id, manifest)
        self.append_event(job_id, "job.failed", stage, message, {"error_code": error_code})
        return manifest

    def list_artifacts(self, job_id: str) -> list[dict[str, Any]]:
        job_root = self.job_root(job_id)
        candidates = [job_root / "project", job_root / "logs", job_root]
        artifacts: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for base in candidates:
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                if path.name in SECRET_NAMES or path.suffix not in ARTIFACT_SUFFIXES:
                    continue
                rel = path.relative_to(job_root).as_posix()
                stat = path.stat()
                artifacts.append(
                    {
                        "name": rel,
                        "size": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat().replace("+00:00", "Z"),
                        "kind": self.artifact_kind(path),
                        "current": True,
                    }
                )
        artifacts.sort(key=lambda item: item["name"])
        return artifacts

    def artifact_path(self, job_id: str, name: str) -> Path:
        if name.startswith("/") or "\x00" in name or ".." in name.split("/"):
            raise StorageError("unsafe artifact name")
        path = assert_inside(self.job_root(job_id) / name, self.job_root(job_id))
        if not path.is_file() or path.name in SECRET_NAMES:
            raise StorageError(f"artifact not found: {name}")
        return path

    def artifact_kind(self, path: Path) -> str:
        parts = set(path.parts)
        if path.suffix == ".mp4":
            return "video"
        if path.suffix in {".wav", ".mp3"}:
            return "audio"
        if path.suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            return "image"
        if "qa" in parts:
            return "qa"
        if path.suffix in {".json", ".jsonl"}:
            return "json"
        if path.suffix == ".log":
            return "log"
        return "text"

    def project_input_hash(self, job_id: str, paths: Iterable[str]) -> str:
        project_root = self.project_root(job_id)
        digest = hashlib.sha256()
        for name in sorted(paths):
            path = project_root / name
            if not path.exists() or not path.is_file():
                continue
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256_file(path).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()
