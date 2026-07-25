from __future__ import annotations

import mimetypes
import socket
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from server.app.core.config import Settings


EICAR_MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
EXECUTABLE_SIGNATURES = (b"MZ", b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xcf\xfa\xed\xfe")
ZIP_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx", ".zip"})
ALLOWED_EXTENSIONS = frozenset(
    {
        ".csv",
        ".doc",
        ".docx",
        ".json",
        ".md",
        ".pdf",
        ".ppt",
        ".pptx",
        ".rtf",
        ".txt",
        ".xls",
        ".xlsx",
        ".zip",
    }
)


class UploadScanError(RuntimeError):
    pass


class UploadScannerUnavailable(UploadScanError):
    pass


@dataclass(frozen=True)
class UploadScanResult:
    status: str
    detected_media_type: str
    scanner: str
    reason: str | None = None


class UploadScanner(Protocol):
    def scan(self, path: Path, *, filename: str, declared_media_type: str | None) -> UploadScanResult: ...


class StructuralUploadScanner:
    """Local structural gate run before the configured malware scanner."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(self, path: Path, *, filename: str, declared_media_type: str | None) -> UploadScanResult:
        extension = Path(filename).suffix.lower()
        detected = _detect_media_type(path, extension)
        if extension not in ALLOWED_EXTENSIONS:
            return UploadScanResult("rejected", detected, "structural", "file extension is not allowed")
        with path.open("rb") as handle:
            prefix = handle.read(8192)
        if prefix.startswith(EXECUTABLE_SIGNATURES):
            return UploadScanResult("infected", detected, "structural", "executable content is not allowed")
        if EICAR_MARKER in prefix:
            return UploadScanResult("infected", detected, "structural", "malware test signature detected")
        if extension == ".pdf" and not prefix.startswith(b"%PDF-"):
            return UploadScanResult("rejected", detected, "structural", "PDF signature does not match extension")
        if extension in ZIP_EXTENSIONS:
            result = self._scan_archive(path, detected)
            if result is not None:
                return result
        if declared_media_type and not _media_types_compatible(declared_media_type, detected, extension):
            return UploadScanResult("rejected", detected, "structural", "declared media type does not match content")
        return UploadScanResult("clean", detected, "structural")

    def _scan_archive(self, path: Path, detected: str) -> UploadScanResult | None:
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > self.settings.max_archive_files:
                    return UploadScanResult("rejected", detected, "structural", "archive contains too many files")
                expanded = 0
                for member in members:
                    name = PurePosixPath(member.filename.replace("\\", "/"))
                    if name.is_absolute() or ".." in name.parts:
                        return UploadScanResult("rejected", detected, "structural", "archive contains an unsafe path")
                    expanded += member.file_size
                    if expanded > self.settings.max_archive_expansion_bytes:
                        return UploadScanResult("rejected", detected, "structural", "archive expands beyond the limit")
                    compressed = max(member.compress_size, 1)
                    if member.file_size / compressed > self.settings.max_archive_compression_ratio:
                        return UploadScanResult("rejected", detected, "structural", "archive compression ratio is unsafe")
        except (OSError, zipfile.BadZipFile):
            return UploadScanResult("rejected", detected, "structural", "archive is invalid")
        return None


class ClamAVUploadScanner:
    """Minimal clamd INSTREAM client; uploaded bytes never enter a shell command."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(self, path: Path, *, filename: str, declared_media_type: str | None) -> UploadScanResult:
        detected = _detect_media_type(path, Path(filename).suffix.lower())
        try:
            with socket.create_connection(
                (self.settings.clamd_host, self.settings.clamd_port),
                timeout=self.settings.clamd_timeout_seconds,
            ) as connection:
                connection.settimeout(self.settings.clamd_timeout_seconds)
                connection.sendall(b"zINSTREAM\0")
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        connection.sendall(struct.pack("!I", len(chunk)))
                        connection.sendall(chunk)
                connection.sendall(struct.pack("!I", 0))
                reply = _read_clamd_reply(connection)
        except (OSError, TimeoutError) as exc:
            raise UploadScannerUnavailable("ClamAV scanner is unavailable") from exc
        if reply.endswith(" OK"):
            return UploadScanResult("clean", detected, "clamav")
        if " FOUND" in reply:
            signature = reply.rsplit(":", 1)[-1].replace("FOUND", "").strip()
            return UploadScanResult("infected", detected, "clamav", signature or "malware detected")
        raise UploadScannerUnavailable("ClamAV returned an indeterminate result")


class CompositeUploadScanner:
    def __init__(self, structural: UploadScanner, malware: UploadScanner | None) -> None:
        self.structural = structural
        self.malware = malware

    def scan(self, path: Path, *, filename: str, declared_media_type: str | None) -> UploadScanResult:
        structural = self.structural.scan(
            path,
            filename=filename,
            declared_media_type=declared_media_type,
        )
        if structural.status != "clean" or self.malware is None:
            return structural
        return self.malware.scan(
            path,
            filename=filename,
            declared_media_type=declared_media_type,
        )


def upload_scanner_from_settings(settings: Settings) -> UploadScanner:
    structural = StructuralUploadScanner(settings)
    if settings.upload_scanner_mode == "structural":
        return CompositeUploadScanner(structural, None)
    if settings.upload_scanner_mode == "clamav":
        return CompositeUploadScanner(structural, ClamAVUploadScanner(settings))
    raise UploadScanError(f"unsupported upload scanner mode: {settings.upload_scanner_mode}")


def _read_clamd_reply(connection: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        chunk = connection.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\0" in chunk or b"\n" in chunk:
            break
    return b"".join(chunks).rstrip(b"\0\r\n").decode("utf-8", errors="replace")


def _detect_media_type(path: Path, extension: str) -> str:
    with path.open("rb") as handle:
        prefix = handle.read(16)
    if prefix.startswith(b"%PDF-"):
        return "application/pdf"
    if prefix.startswith(b"PK\x03\x04"):
        office_types = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        return office_types.get(extension, "application/zip")
    if prefix.startswith(b"{\\rtf"):
        return "application/rtf"
    guessed = mimetypes.guess_type(path.name)[0] or mimetypes.guess_type(f"file{extension}")[0]
    return guessed or "application/octet-stream"


def _media_types_compatible(declared: str, detected: str, extension: str) -> bool:
    normalized = declared.split(";", 1)[0].strip().lower()
    if normalized == detected.lower():
        return True
    if normalized in {"application/octet-stream", "binary/octet-stream"}:
        return True
    if extension in {".txt", ".md", ".csv", ".json"} and normalized.startswith("text/"):
        return True
    if extension in ZIP_EXTENSIONS and normalized in {"application/zip", "application/x-zip-compressed"}:
        return True
    return False
