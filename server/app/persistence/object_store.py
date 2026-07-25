from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Protocol

from server.app.core.config import Settings


class ObjectStoreError(RuntimeError):
    pass


class ObjectNotFound(ObjectStoreError):
    pass


class InvalidObjectKey(ObjectStoreError):
    pass


class SignedObjectTokenError(ObjectStoreError):
    pass


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    sha256: str
    media_type: str
    modified_at: datetime


class ObjectStore(Protocol):
    def put_file(self, key: str, source: Path, *, media_type: str | None = None) -> ObjectMetadata: ...

    def put_bytes(self, key: str, content: bytes, *, media_type: str) -> ObjectMetadata: ...

    def head(self, key: str) -> ObjectMetadata: ...

    def open(self, key: str) -> BinaryIO: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str = "") -> Iterable[ObjectMetadata]: ...

    def presign_get(self, key: str, *, expires_seconds: int) -> str | None: ...


def validate_object_key(key: str) -> str:
    if not key or key.startswith("/") or "\\" in key or "\x00" in key:
        raise InvalidObjectKey("object key must be a non-empty relative POSIX path")
    path = PurePosixPath(key)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidObjectKey("object key contains an unsafe path segment")
    return path.as_posix()


def object_key_for_artifact(
    tenant_id: str,
    job_id: str,
    revision_id: str,
    logical_name: str,
) -> str:
    for value, label in ((tenant_id, "tenant"), (job_id, "job"), (revision_id, "revision")):
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise InvalidObjectKey(f"unsafe {label} identifier")
    logical_path = validate_object_key(logical_name)
    return validate_object_key(
        f"tenants/{tenant_id}/jobs/{job_id}/pending/{revision_id}/{logical_path}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_from_timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc)


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        normalized = validate_object_key(key)
        path = (self.root / normalized).resolve()
        if self.root not in path.parents:
            raise InvalidObjectKey("object key escapes the configured root")
        return path

    def put_file(self, key: str, source: Path, *, media_type: str | None = None) -> ObjectMetadata:
        source = source.resolve()
        if not source.is_file():
            raise ObjectNotFound(f"source file does not exist: {source}")
        target = self._path(key)
        expected_sha = sha256_file(source)
        expected_size = source.stat().st_size
        if target.exists():
            current = self.head(key)
            if current.sha256 != expected_sha or current.size_bytes != expected_size:
                raise ObjectStoreError("immutable object key already contains different content")
            return current
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_handle, tempfile.NamedTemporaryFile(
            "wb", dir=str(target.parent), delete=False
        ) as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
            temporary = Path(output_handle.name)
        os.replace(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return self._metadata(target, key, media_type=media_type)

    def put_bytes(self, key: str, content: bytes, *, media_type: str) -> ObjectMetadata:
        target = self._path(key)
        expected_sha = hashlib.sha256(content).hexdigest()
        if target.exists():
            current = self.head(key)
            if current.sha256 != expected_sha or current.size_bytes != len(content):
                raise ObjectStoreError("immutable object key already contains different content")
            return current
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=str(target.parent), delete=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, target)
        return self._metadata(target, key, media_type=media_type)

    def head(self, key: str) -> ObjectMetadata:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(f"object not found: {key}")
        return self._metadata(path, key)

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(f"object not found: {key}")
        return path.open("rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def list(self, prefix: str = "") -> Iterable[ObjectMetadata]:
        if prefix:
            normalized = validate_object_key(prefix.rstrip("/"))
            start = self._path(normalized)
        else:
            start = self.root
        if start.is_file():
            yield self._metadata(start, start.relative_to(self.root).as_posix())
            return
        if not start.exists():
            return
        for path in sorted(item for item in start.rglob("*") if item.is_file()):
            key = path.relative_to(self.root).as_posix()
            yield self._metadata(path, key)

    def presign_get(self, key: str, *, expires_seconds: int) -> str | None:
        self.head(key)
        return None

    @staticmethod
    def _metadata(path: Path, key: str, *, media_type: str | None = None) -> ObjectMetadata:
        stat = path.stat()
        detected = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return ObjectMetadata(
            key=validate_object_key(key),
            size_bytes=stat.st_size,
            sha256=sha256_file(path),
            media_type=detected,
            modified_at=_utc_from_timestamp(stat.st_mtime),
        )


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str | None,
        secret_key: str | None,
    ) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - exercised in deployment image
            raise ObjectStoreError("boto3 is required for the s3 object-store backend") from exc
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def put_file(self, key: str, source: Path, *, media_type: str | None = None) -> ObjectMetadata:
        normalized = validate_object_key(key)
        digest = sha256_file(source)
        size = source.stat().st_size
        try:
            current = self.head(normalized)
        except ObjectNotFound:
            current = None
        if current is not None:
            if current.sha256 != digest or current.size_bytes != size:
                raise ObjectStoreError("immutable object key already contains different content")
            return current
        content_type = media_type or mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        with source.open("rb") as handle:
            self.client.upload_fileobj(
                handle,
                self.bucket,
                normalized,
                ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": digest}},
            )
        return self.head(normalized)

    def put_bytes(self, key: str, content: bytes, *, media_type: str) -> ObjectMetadata:
        normalized = validate_object_key(key)
        digest = hashlib.sha256(content).hexdigest()
        try:
            current = self.head(normalized)
        except ObjectNotFound:
            current = None
        if current is not None:
            if current.sha256 != digest or current.size_bytes != len(content):
                raise ObjectStoreError("immutable object key already contains different content")
            return current
        self.client.put_object(
            Bucket=self.bucket,
            Key=normalized,
            Body=content,
            ContentType=media_type,
            Metadata={"sha256": digest},
        )
        return self.head(normalized)

    def head(self, key: str) -> ObjectMetadata:
        normalized = validate_object_key(key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:  # boto3 exception classes are optional at import time
            status = getattr(getattr(exc, "response", {}), "get", lambda *_: {}) ("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            if status == 404:
                raise ObjectNotFound(f"object not found: {normalized}") from exc
            raise ObjectStoreError(f"failed to inspect object {normalized}") from exc
        digest = response.get("Metadata", {}).get("sha256")
        if not digest:
            raise ObjectStoreError(f"object {normalized} has no sha256 metadata")
        modified = response["LastModified"]
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        return ObjectMetadata(
            key=normalized,
            size_bytes=int(response["ContentLength"]),
            sha256=digest,
            media_type=response.get("ContentType") or "application/octet-stream",
            modified_at=modified.astimezone(timezone.utc),
        )

    def open(self, key: str) -> BinaryIO:
        normalized = validate_object_key(key)
        try:
            return self.client.get_object(Bucket=self.bucket, Key=normalized)["Body"]
        except Exception as exc:
            raise ObjectNotFound(f"object not found: {normalized}") from exc

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=validate_object_key(key))

    def list(self, prefix: str = "") -> Iterable[ObjectMetadata]:
        normalized = validate_object_key(prefix.rstrip("/")) if prefix else ""
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=normalized):
            for item in page.get("Contents", []):
                yield self.head(item["Key"])

    def presign_get(self, key: str, *, expires_seconds: int) -> str | None:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": validate_object_key(key)},
            ExpiresIn=expires_seconds,
        )


class SignedObjectTokenService:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 16:
            raise SignedObjectTokenError("object signing secret must be at least 16 bytes")
        self.secret = secret

    def issue(self, *, tenant_id: str, job_id: str, object_key: str, expires_at: int) -> str:
        payload = {
            "tenant_id": tenant_id,
            "job_id": job_id,
            "object_key": validate_object_key(object_key),
            "exp": int(expires_at),
        }
        encoded = self._b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = self._b64(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(
        self,
        token: str,
        *,
        tenant_id: str,
        job_id: str,
        now_epoch: int,
    ) -> dict[str, object]:
        try:
            encoded, signature = token.split(".", 1)
            expected = self._b64(hmac.new(self.secret, encoded.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise SignedObjectTokenError("invalid object token signature")
            payload = json.loads(self._unb64(encoded))
        except SignedObjectTokenError:
            raise
        except Exception as exc:
            raise SignedObjectTokenError("malformed object token") from exc
        if payload.get("tenant_id") != tenant_id or payload.get("job_id") != job_id:
            raise SignedObjectTokenError("object token tenant or job mismatch")
        if int(payload.get("exp", 0)) < int(now_epoch):
            raise SignedObjectTokenError("object token expired")
        payload["object_key"] = validate_object_key(str(payload.get("object_key", "")))
        return payload

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _unb64(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)


def object_store_from_settings(settings: Settings) -> ObjectStore:
    if settings.object_store_backend == "local":
        return LocalObjectStore(settings.object_store_root)
    if settings.object_store_backend in {"s3", "minio"}:
        return S3ObjectStore(
            bucket=settings.object_store_bucket,
            endpoint_url=settings.object_store_endpoint,
            region=settings.object_store_region,
            access_key=os.getenv(settings.object_store_access_key_env),
            secret_key=os.getenv(settings.object_store_secret_key_env),
        )
    raise ObjectStoreError(f"unsupported object store backend: {settings.object_store_backend}")
