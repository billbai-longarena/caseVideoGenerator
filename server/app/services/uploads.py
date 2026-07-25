from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Any

from server.app.core.config import Settings
from server.app.core.errors import AppError
from server.app.models.job import CreateUploadRequest, utc_now_iso
from server.app.services.storage import atomic_write_json, exclusive_file_lock, sha256_file


SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".json": {"application/json", "text/json", "text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    ".zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
}


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def safe_upload_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem
    cleaned = SAFE_COMPONENT.sub("-", stem).strip(".-")[:180] or "source"
    return f"{cleaned}{suffix}"


def detect_media_type(path: Path, suffix: str) -> str:
    with path.open("rb") as handle:
        head = handle.read(8192)
    if suffix == ".pdf":
        if not head.startswith(b"%PDF-"):
            raise AppError("source_invalid", "PDF signature does not match the filename")
        return "application/pdf"
    if suffix in {".docx", ".zip"}:
        if not head.startswith(b"PK") or not zipfile.is_zipfile(path):
            raise AppError("source_invalid", "ZIP signature does not match the filename")
        if suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise AppError("source_invalid", "DOCX package is missing required document parts")
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return "application/zip"
    if b"\x00" in head:
        raise AppError("source_invalid", "text source contains binary data")
    try:
        head.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("source_invalid", "text source must be UTF-8") from exc
    if suffix == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppError("source_invalid", "JSON source is not valid UTF-8 JSON") from exc
        return "application/json"
    return "text/markdown" if suffix == ".md" else "text/plain"


class UploadStorage:
    """Durable local upload quarantine used by the Phase B API.

    Upload bytes never use the user supplied filename as a path.  A completed
    upload is immutable; a job binds it by id and copies it into its own source
    directory before extraction.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.data_root / "_uploads"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, request: CreateUploadRequest) -> dict[str, Any]:
        suffix = Path(request.filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise AppError(
                "source_invalid",
                f"unsupported upload type: {suffix or '(no extension)'}",
                diagnostics={"filename": request.filename},
            )
        if request.size_bytes > self.settings.max_upload_bytes:
            raise AppError("source_invalid", "upload exceeds the configured size limit", status_code=413)
        declared = (request.media_type or "application/octet-stream").split(";", 1)[0].strip().lower()
        if declared not in ALLOWED_EXTENSIONS[suffix]:
            raise AppError("source_invalid", "declared media type does not match the file extension")

        upload_id = f"upl_{uuid.uuid4().hex}"
        created = datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "upload_id": upload_id,
            "filename": request.filename,
            "safe_name": safe_upload_name(request.filename),
            "suffix": suffix,
            "declared_size_bytes": request.size_bytes,
            "size_bytes": None,
            "declared_media_type": request.media_type,
            "detected_media_type": None,
            "declared_sha256": request.sha256,
            "sha256": None,
            "status": "pending",
            "max_size_bytes": self.settings.max_upload_bytes,
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "expires_at": (created + timedelta(seconds=self.settings.upload_ttl_seconds)).isoformat().replace(
                "+00:00", "Z"
            ),
            "bound_job_id": None,
        }
        self.upload_root(upload_id).mkdir(parents=True, exist_ok=False)
        atomic_write_json(self.metadata_path(upload_id), record)
        return record

    async def put(self, upload_id: str, chunks: AsyncIterator[bytes]) -> dict[str, Any]:
        record = self.get(upload_id)
        self._assert_mutable(record)
        destination = self.data_path(upload_id)
        digest = hashlib.sha256()
        size = 0
        fd, temp_name = tempfile.mkstemp(prefix="upload-", suffix=".part", dir=str(destination.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes or size > record["declared_size_bytes"]:
                        raise AppError("source_invalid", "uploaded bytes exceed the declared or configured size", status_code=413)
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise AppError("source_invalid", "upload must not be empty")
            if size != record["declared_size_bytes"]:
                raise AppError(
                    "source_invalid",
                    f"uploaded size {size} does not match declared size {record['declared_size_bytes']}",
                )
            actual_sha = digest.hexdigest()
            if record.get("declared_sha256") and record["declared_sha256"] != actual_sha:
                raise AppError("source_invalid", "uploaded sha256 does not match the declared checksum")
            os.replace(temp_name, destination)
            detected = detect_media_type(destination, record["suffix"])
            updated = {
                **record,
                "size_bytes": size,
                "sha256": actual_sha,
                "detected_media_type": detected,
                "status": "complete",
                "completed_at": utc_now_iso(),
            }
            atomic_write_json(self.metadata_path(upload_id), updated)
            return updated
        except Exception:
            Path(temp_name).unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def get(self, upload_id: str) -> dict[str, Any]:
        path = self.metadata_path(upload_id)
        if not path.is_file():
            raise AppError("not_found", f"upload not found: {upload_id}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if _parse_iso(record["expires_at"]) <= datetime.now(timezone.utc) and not record.get("bound_job_id"):
            raise AppError("upload_expired", f"upload expired: {upload_id}")
        return record

    def delete(self, upload_id: str) -> None:
        record = self.get(upload_id)
        if record.get("bound_job_id"):
            raise AppError("upload_bound", "upload is already bound to a job")
        root = self.upload_root(upload_id)
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()

    def bind(self, upload_id: str, job_id: str) -> dict[str, Any]:
        lock = self.upload_root(upload_id) / ".lock"
        with exclusive_file_lock(lock):
            record = self.get(upload_id)
            if record["status"] != "complete":
                raise AppError("upload_incomplete", f"upload is not complete: {upload_id}")
            bound = record.get("bound_job_id")
            if bound and bound != job_id:
                raise AppError("upload_bound", f"upload is already bound to another job: {upload_id}")
            if not bound:
                record["bound_job_id"] = job_id
                record["bound_at"] = utc_now_iso()
                atomic_write_json(self.metadata_path(upload_id), record)
            return record

    def cleanup_expired(self, *, now: datetime | None = None) -> list[str]:
        effective_now = now or datetime.now(timezone.utc)
        removed: list[str] = []
        for metadata in self.root.glob("upl_*/metadata.json"):
            try:
                record = json.loads(metadata.read_text(encoding="utf-8"))
                if not record.get("bound_job_id") and _parse_iso(record["expires_at"]) <= effective_now:
                    upload_id = record["upload_id"]
                    root = metadata.parent
                    for path in sorted(root.rglob("*"), reverse=True):
                        if path.is_file():
                            path.unlink()
                        elif path.is_dir():
                            path.rmdir()
                    root.rmdir()
                    removed.append(upload_id)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return removed

    def upload_root(self, upload_id: str) -> Path:
        if not upload_id.startswith("upl_") or not upload_id.replace("_", "").isalnum():
            raise AppError("not_found", "invalid upload id")
        path = (self.root / upload_id).resolve()
        if self.root.resolve() not in path.parents:
            raise AppError("not_found", "invalid upload id")
        return path

    def metadata_path(self, upload_id: str) -> Path:
        return self.upload_root(upload_id) / "metadata.json"

    def data_path(self, upload_id: str) -> Path:
        return self.upload_root(upload_id) / "payload.bin"

    def _assert_mutable(self, record: dict[str, Any]) -> None:
        if record.get("bound_job_id"):
            raise AppError("upload_bound", "upload is already bound to a job")
        if record["status"] == "complete":
            raise AppError("upload_bound", "completed uploads are immutable")

    def verify_bytes(self, upload_id: str) -> None:
        record = self.get(upload_id)
        path = self.data_path(upload_id)
        if not path.is_file() or sha256_file(path) != record.get("sha256"):
            raise AppError("artifact_corrupt", f"upload bytes failed checksum verification: {upload_id}")
