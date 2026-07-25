from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from server.app.core.errors import AppError
from server.app.persistence.artifact_commit import ArtifactCommitService, ArtifactSource
from server.app.persistence.object_store import sha256_file
from server.app.persistence.repository import (
    PhaseCRepository,
    RepositoryConflict,
    RepositoryNotFound,
    sha256_json,
)
from server.app.services.contracts import ContractRegistry, canonical_json


SKIP_NAMES = {".env", ".env.local", ".env.production", ".case-video.lock", ".DS_Store"}
SKIP_PARTS = {"__pycache__", "node_modules", ".git", "tmp", "cache"}
SUPPORTED_MANIFEST_VERSION = 2
SUPPORTED_REVISION_METADATA_VERSION = 1
SUPPORTED_REVISION_DOMAINS = {
    "case-model": "case_model",
    "editorial": "editorial",
    "visual-plan": "visual_plan",
}
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


@dataclass
class ImportCandidate:
    job_id: str
    root: str
    valid: bool
    artifact_count: int
    total_bytes: int
    action: str
    source_count: int = 0
    revision_count: int = 0
    hash_mismatch: bool = False
    unsupported_schema: bool = False
    shadow_status: str = "not_run"
    source_snapshot_sha256: str | None = None
    database_artifact_count: int = 0
    object_verified_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    dry_run: bool
    tenant_id: str
    source_root: str
    shadow_only: bool = False
    candidates: list[ImportCandidate] = field(default_factory=list)

    @property
    def imported(self) -> int:
        return sum(1 for item in self.candidates if item.action == "imported")

    @property
    def verified(self) -> int:
        return sum(1 for item in self.candidates if item.action == "verified")

    @property
    def skipped(self) -> int:
        return sum(1 for item in self.candidates if item.action == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.candidates if item.action == "failed")

    def to_dict(self) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for item in self.candidates:
            payload = asdict(item)
            payload["final_status"] = item.action
            candidates.append(payload)
        return {
            "dry_run": self.dry_run,
            "shadow_only": self.shadow_only,
            "tenant_id": self.tenant_id,
            "source_root": self.source_root,
            "summary": {
                "candidate_count": len(self.candidates),
                "imported": self.imported,
                "verified": self.verified,
                "skipped": self.skipped,
                "failed": self.failed,
                "source_count": sum(item.source_count for item in self.candidates),
                "revision_count": sum(item.revision_count for item in self.candidates),
                "artifact_count": sum(item.artifact_count for item in self.candidates),
                "total_bytes": sum(item.total_bytes for item in self.candidates),
                "hash_mismatch": sum(1 for item in self.candidates if item.hash_mismatch),
                "unsupported_schema": sum(1 for item in self.candidates if item.unsupported_schema),
                "shadow_verified": sum(
                    1 for item in self.candidates if item.shadow_status == "passed"
                ),
            },
            "candidates": candidates,
        }


@dataclass(frozen=True)
class _FileFact:
    logical_name: str
    path: Path
    size_bytes: int
    sha256: str


@dataclass
class _Validation:
    source_count: int = 0
    revision_count: int = 0
    hash_mismatch: bool = False
    unsupported_schema: bool = False
    errors: list[str] = field(default_factory=list)

    def fail(
        self,
        message: str,
        *,
        hash_mismatch: bool = False,
        unsupported_schema: bool = False,
    ) -> None:
        self.errors.append(message)
        self.hash_mismatch = self.hash_mismatch or hash_mismatch
        self.unsupported_schema = self.unsupported_schema or unsupported_schema


@dataclass(frozen=True)
class _Inspection:
    candidate: ImportCandidate
    manifest: dict[str, Any]
    normalized_manifest: dict[str, Any]
    artifacts: tuple[_FileFact, ...]
    source_snapshot_sha256: str


@dataclass(frozen=True)
class _ShadowResult:
    passed: bool
    hash_mismatch: bool
    errors: tuple[str, ...]
    database_artifact_count: int
    object_verified_count: int


class LegacyJobImporter:
    """Import filesystem-authoritative jobs into Phase C persistence.

    Source bytes are inspected once and treated as immutable facts. Declared
    checksums are verified before upload, then SQL metadata and object bytes
    are compared against the captured facts before the job is eligible for a
    cutover. Re-running the command is idempotent because the artifact revision
    ID derives from the complete captured inventory.
    """

    def __init__(
        self,
        repository: PhaseCRepository,
        artifacts: ArtifactCommitService,
        *,
        contracts: ContractRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        schema_root = Path(__file__).resolve().parents[2] / "schemas"
        self.contracts = contracts or ContractRegistry(schema_root)

    def run(
        self,
        source_root: Path,
        *,
        tenant_id: str,
        actor_id: str,
        dry_run: bool,
        shadow_only: bool = False,
    ) -> ImportReport:
        if dry_run and shadow_only:
            raise ValueError("dry_run and shadow_only are mutually exclusive")
        source_root = source_root.resolve()
        report = ImportReport(
            dry_run=dry_run,
            shadow_only=shadow_only,
            tenant_id=tenant_id,
            source_root=str(source_root),
        )
        if not source_root.is_dir():
            report.candidates.append(
                ImportCandidate(
                    job_id="",
                    root=str(source_root),
                    valid=False,
                    artifact_count=0,
                    total_bytes=0,
                    action="failed",
                    errors=["source root does not exist"],
                )
            )
            return report

        # A dry run is genuinely read-only. Tenant creation is part of the
        # actual import boundary, never validation or shadow verification.
        if not dry_run and not shadow_only:
            self.repository.ensure_tenant(tenant_id, name=tenant_id)
        roots = sorted(
            path
            for path in source_root.iterdir()
            if (path.is_dir() or path.is_symlink()) and not path.name.startswith("_")
        )
        for job_root in roots:
            inspection = self._inspect(job_root)
            candidate = inspection.candidate
            report.candidates.append(candidate)
            if not candidate.valid:
                candidate.action = "failed"
                continue
            if dry_run:
                candidate.action = "validated"
                continue
            if shadow_only:
                shadow = self._shadow_verify(inspection, tenant_id=tenant_id)
                self._apply_shadow_result(candidate, shadow, success_action="verified")
                continue
            try:
                revision_id = self._import_one(
                    inspection,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                )
                current_snapshot = self._source_snapshot(job_root)
                if current_snapshot != inspection.source_snapshot_sha256:
                    candidate.hash_mismatch = True
                    candidate.valid = False
                    candidate.action = "failed"
                    candidate.shadow_status = "blocked"
                    candidate.errors.append(
                        "source snapshot changed while import was running; cutover is blocked"
                    )
                    continue
                shadow = self._shadow_verify(
                    inspection,
                    tenant_id=tenant_id,
                    expected_revision_id=revision_id,
                )
                self._apply_shadow_result(candidate, shadow, success_action="imported")
            except Exception as exc:
                candidate.action = "failed"
                candidate.shadow_status = "blocked"
                candidate.errors.append(str(exc))
        return report

    def _inspect(self, job_root: Path) -> _Inspection:
        validation = _Validation()
        manifest: dict[str, Any] = {}
        artifacts: tuple[_FileFact, ...] = ()
        source_snapshot = ""
        try:
            all_files, migratable = self._scan_job_files(job_root)
            artifacts = tuple(migratable)
            source_snapshot = self._inventory_sha256(all_files)
        except (OSError, ValueError) as exc:
            validation.fail(f"source scan failed: {exc}")

        manifest_path = job_root / "job_manifest.json"
        if not manifest_path.is_file():
            validation.fail("job_manifest.json is missing")
        else:
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("manifest root must be an object")
                manifest = loaded
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                validation.fail(f"invalid manifest: {exc}")

        job_id = str(manifest.get("job_id") or job_root.name)
        if manifest and manifest.get("job_id") != job_root.name:
            validation.fail("manifest job_id does not match directory name")
        if manifest:
            self._validate_manifest(manifest, validation)
            self._validate_source_manifest(job_root, manifest, validation)
            self._validate_revisions(job_root, manifest, validation)
            self._validate_artifact_index(job_root, manifest, validation)

        candidate = ImportCandidate(
            job_id=job_id,
            root=str(job_root),
            valid=not validation.errors,
            artifact_count=len(artifacts),
            total_bytes=sum(item.size_bytes for item in artifacts),
            action="pending",
            source_count=validation.source_count,
            revision_count=validation.revision_count,
            hash_mismatch=validation.hash_mismatch,
            unsupported_schema=validation.unsupported_schema,
            source_snapshot_sha256=source_snapshot or None,
            errors=validation.errors,
        )
        normalized = self._normalize_manifest(manifest, job_root.name) if manifest else {}
        return _Inspection(
            candidate=candidate,
            manifest=manifest,
            normalized_manifest=normalized,
            artifacts=artifacts,
            source_snapshot_sha256=source_snapshot,
        )

    def _validate_manifest(self, manifest: dict[str, Any], validation: _Validation) -> None:
        version = manifest.get("manifest_version")
        if version != SUPPORTED_MANIFEST_VERSION:
            validation.fail(
                f"unsupported job manifest schema version: {version!r}",
                unsupported_schema=True,
            )
            return
        try:
            self.contracts.validate("job_manifest", "v2", manifest)
        except AppError as exc:
            validation.fail(f"job manifest schema validation failed: {exc}")
        self._validate_contract_versions(manifest.get("contract_versions"), validation)

    def _validate_contract_versions(self, versions: Any, validation: _Validation) -> None:
        if not isinstance(versions, dict):
            return
        for name, raw_version in sorted(versions.items()):
            version = str(raw_version)
            normalized = version if version.startswith("v") else f"v{version}"
            try:
                self.contracts.ref(str(name), normalized)
            except AppError:
                validation.fail(
                    f"unsupported contract schema: {name}/{version}",
                    unsupported_schema=True,
                )

    def _validate_source_manifest(
        self,
        job_root: Path,
        manifest: dict[str, Any],
        validation: _Validation,
    ) -> None:
        source_manifest_path = job_root / "source" / "source_manifest.json"
        if not source_manifest_path.is_file():
            inputs = manifest.get("inputs", {})
            if isinstance(inputs, dict):
                uploads = inputs.get("upload_ids", [])
                validation.source_count = len(uploads) if isinstance(uploads, list) else 0
                validation.source_count += int(bool(inputs.get("has_structured_input")))
            return
        try:
            source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            validation.fail(f"invalid source manifest: {exc}")
            return
        if not isinstance(source_manifest, dict):
            validation.fail("source manifest root must be an object")
            return
        version = source_manifest.get("version")
        if version != "1":
            validation.fail(
                f"unsupported source manifest schema version: {version!r}",
                unsupported_schema=True,
            )
            return
        try:
            self.contracts.validate("source_manifest", "v1", source_manifest)
        except AppError as exc:
            validation.fail(f"source manifest schema validation failed: {exc}")
            return
        records = source_manifest.get("files", [])
        validation.source_count = len(records)
        for record in records:
            source_id = str(record["source_id"])
            if record.get("upload_id") is None and record.get("safe_name") == "structured_input.json":
                original = job_root / "source" / "structured_input.json"
            else:
                originals = job_root / "source" / "originals"
                matches = [
                    path
                    for path in originals.glob(f"{source_id}*")
                    if path.is_file() and (path.name == source_id or path.name.startswith(f"{source_id}."))
                ]
                if len(matches) != 1:
                    validation.fail(
                        f"source {source_id} does not resolve to exactly one original file",
                        hash_mismatch=True,
                    )
                    original = None
                else:
                    original = matches[0]
            if original is not None:
                self._verify_declared_file(
                    original,
                    label=f"source {source_id}",
                    expected_size=record.get("size_bytes"),
                    expected_sha256=record.get("sha256"),
                    validation=validation,
                )
            extracted_sha = record.get("extracted_text_sha256")
            if extracted_sha:
                self._verify_declared_file(
                    job_root / "source" / "extracted" / f"{source_id}.txt",
                    label=f"extracted source {source_id}",
                    expected_size=None,
                    expected_sha256=extracted_sha,
                    validation=validation,
                )

    def _validate_revisions(
        self,
        job_root: Path,
        manifest: dict[str, Any],
        validation: _Validation,
    ) -> None:
        revisions_root = job_root / "revisions"
        discovered: dict[str, set[str]] = {key: set() for key in SUPPORTED_REVISION_DOMAINS}
        parents: list[tuple[str, str, str]] = []
        if revisions_root.is_dir():
            for domain_root in sorted(path for path in revisions_root.iterdir() if path.is_dir()):
                domain = domain_root.name
                if domain not in SUPPORTED_REVISION_DOMAINS:
                    validation.fail(
                        f"unsupported revision domain: {domain}",
                        unsupported_schema=True,
                    )
                for revision_root in sorted(path for path in domain_root.iterdir() if path.is_dir()):
                    if revision_root.name.startswith("."):
                        continue
                    validation.revision_count += 1
                    discovered.setdefault(domain, set()).add(revision_root.name)
                    metadata_path = revision_root / "metadata.json"
                    if not metadata_path.is_file():
                        validation.fail(
                            f"revision {domain}/{revision_root.name} is missing metadata.json"
                        )
                        continue
                    try:
                        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        validation.fail(
                            f"invalid revision metadata {domain}/{revision_root.name}: {exc}"
                        )
                        continue
                    if not isinstance(metadata, dict):
                        validation.fail(
                            f"revision metadata {domain}/{revision_root.name} must be an object"
                        )
                        continue
                    if metadata.get("metadata_version") != SUPPORTED_REVISION_METADATA_VERSION:
                        validation.fail(
                            f"unsupported revision metadata schema: {domain}/{revision_root.name} "
                            f"version {metadata.get('metadata_version')!r}",
                            unsupported_schema=True,
                        )
                        continue
                    if metadata.get("revision_id") != revision_root.name:
                        validation.fail(
                            f"revision metadata ID mismatch: {domain}/{revision_root.name}"
                        )
                    if metadata.get("domain") != domain:
                        validation.fail(
                            f"revision metadata domain mismatch: {domain}/{revision_root.name}"
                        )
                    self._validate_contract_versions(metadata.get("schema_versions"), validation)
                    content_hashes = metadata.get("content_hashes")
                    if not isinstance(content_hashes, dict):
                        validation.fail(
                            f"revision {domain}/{revision_root.name} has invalid content_hashes"
                        )
                        continue
                    declared_names = set(content_hashes)
                    actual_names = {
                        path.relative_to(revision_root).as_posix()
                        for path in revision_root.rglob("*")
                        if path.is_file() and path.name != "metadata.json"
                    }
                    if actual_names != declared_names:
                        validation.fail(
                            f"revision {domain}/{revision_root.name} content declaration differs "
                            "from the files on disk",
                            hash_mismatch=True,
                        )
                    for name, expected_sha in sorted(content_hashes.items()):
                        path = self._safe_child(revision_root, str(name))
                        if path is None:
                            validation.fail(
                                f"revision {domain}/{revision_root.name} has unsafe content path: {name}",
                                hash_mismatch=True,
                            )
                            continue
                        self._verify_declared_file(
                            path,
                            label=f"revision {domain}/{revision_root.name}/{name}",
                            expected_size=None,
                            expected_sha256=expected_sha,
                            validation=validation,
                        )
                    expected_content_sha = hashlib.sha256(
                        canonical_json(content_hashes).encode("utf-8")
                    ).hexdigest()
                    if metadata.get("content_sha256") != expected_content_sha:
                        validation.fail(
                            f"revision {domain}/{revision_root.name} content_sha256 mismatch",
                            hash_mismatch=True,
                        )
                    if metadata.get("etag") != expected_content_sha:
                        validation.fail(
                            f"revision {domain}/{revision_root.name} etag mismatch",
                            hash_mismatch=True,
                        )
                    parent = metadata.get("parent_revision")
                    if parent:
                        parents.append((domain, revision_root.name, str(parent)))

        for domain, revision_id, parent_id in parents:
            if parent_id not in discovered.get(domain, set()):
                validation.fail(
                    f"revision {domain}/{revision_id} references missing parent {parent_id}"
                )
        current = manifest.get("current_revisions", {})
        approved = manifest.get("approved_revisions", {})
        for domain, manifest_key in SUPPORTED_REVISION_DOMAINS.items():
            for pointer_name, pointers in (("current", current), ("approved", approved)):
                if not isinstance(pointers, dict):
                    continue
                revision_id = pointers.get(manifest_key)
                if revision_id and revision_id not in discovered.get(domain, set()):
                    validation.fail(
                        f"{pointer_name} revision pointer {manifest_key} references missing "
                        f"revision {revision_id}"
                    )

    def _validate_artifact_index(
        self,
        job_root: Path,
        manifest: dict[str, Any],
        validation: _Validation,
    ) -> None:
        index_path = job_root / "artifact_index.json"
        declared_index_sha = manifest.get("artifact_index_sha256")
        if declared_index_sha:
            self._verify_declared_file(
                index_path,
                label="artifact_index.json",
                expected_size=None,
                expected_sha256=declared_index_sha,
                validation=validation,
            )
        elif index_path.is_file():
            validation.fail("artifact_index.json exists but the manifest does not declare its sha256")
        if not index_path.is_file():
            return
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            validation.fail(f"invalid artifact index: {exc}")
            return
        if not isinstance(index, dict):
            validation.fail("artifact index root must be an object")
            return
        if index.get("version") != "1":
            validation.fail(
                f"unsupported artifact index schema version: {index.get('version')!r}",
                unsupported_schema=True,
            )
            return
        try:
            self.contracts.validate("artifact_index", "v1", index)
        except AppError as exc:
            validation.fail(f"artifact index schema validation failed: {exc}")
            return
        names: set[str] = set()
        for item in index.get("artifacts", []):
            name = str(item["name"])
            if name in names:
                validation.fail(f"artifact index contains duplicate name: {name}")
                continue
            names.add(name)
            path = self._safe_child(job_root, name)
            if path is None:
                validation.fail(f"artifact index contains unsafe path: {name}")
                continue
            self._verify_declared_file(
                path,
                label=f"artifact {name}",
                expected_size=item.get("size"),
                expected_sha256=item.get("sha256"),
                validation=validation,
            )

    @staticmethod
    def _verify_declared_file(
        path: Path,
        *,
        label: str,
        expected_size: Any,
        expected_sha256: Any,
        validation: _Validation,
    ) -> None:
        if not path.is_file() or path.is_symlink():
            validation.fail(f"{label} is missing", hash_mismatch=True)
            return
        if not isinstance(expected_sha256, str) or not SHA256_PATTERN.fullmatch(expected_sha256):
            validation.fail(f"{label} has an invalid declared sha256")
            return
        stat = path.stat()
        if expected_size is not None and stat.st_size != expected_size:
            validation.fail(f"{label} size mismatch", hash_mismatch=True)
        if sha256_file(path) != expected_sha256:
            validation.fail(f"{label} sha256 mismatch", hash_mismatch=True)

    def _import_one(
        self,
        inspection: _Inspection,
        *,
        tenant_id: str,
        actor_id: str,
    ) -> str:
        manifest = copy.deepcopy(inspection.normalized_manifest)
        job_root = Path(inspection.candidate.root)
        try:
            existing = self.repository.get_job(tenant_id, manifest["job_id"], include_deleted=True)
        except RepositoryNotFound:
            self.repository.create_job(
                tenant_id,
                manifest,
                request_hash=sha256_json(
                    {
                        "migration_source_snapshot": inspection.source_snapshot_sha256,
                        "manifest": manifest,
                    }
                ),
                engine_snapshot={"migration": "phase-b-filesystem-v2"},
            )
        else:
            if existing.get("project_name") != manifest.get("project_name"):
                raise RepositoryConflict("existing job has different project metadata")

        revision_id = self._revision_id(manifest["job_id"], inspection.artifacts)
        sources = [
            ArtifactSource(
                logical_name=item.logical_name,
                path=item.path,
                media_type=mimetypes.guess_type(item.path.name)[0],
            )
            for item in inspection.artifacts
        ]
        if not sources:
            raise ValueError("migration source contains no importable files")
        self.artifacts.commit(
            tenant_id=tenant_id,
            job_id=manifest["job_id"],
            domain="migration.snapshot",
            revision_id=revision_id,
            sources=sources,
            created_by=actor_id,
        )
        self.repository.audit(
            tenant_id,
            actor_id=actor_id,
            action="migration.import_job",
            resource_type="job",
            resource_id=manifest["job_id"],
            result="succeeded",
            payload={
                "source_root": str(job_root),
                "source_snapshot_sha256": inspection.source_snapshot_sha256,
                "source_count": inspection.candidate.source_count,
                "revision_count": inspection.candidate.revision_count,
                "artifact_count": len(sources),
                "total_bytes": inspection.candidate.total_bytes,
            },
        )
        return revision_id

    def _shadow_verify(
        self,
        inspection: _Inspection,
        *,
        tenant_id: str,
        expected_revision_id: str | None = None,
    ) -> _ShadowResult:
        errors: list[str] = []
        object_verified = 0
        expected_manifest = inspection.normalized_manifest
        expected_revision = expected_revision_id or self._revision_id(
            expected_manifest["job_id"], inspection.artifacts
        )
        try:
            database_job = self.repository.get_job(
                tenant_id,
                expected_manifest["job_id"],
                include_deleted=True,
            )
        except RepositoryNotFound:
            return _ShadowResult(False, False, ("database job is missing",), 0, 0)
        actual_manifest = self._normalize_manifest(database_job, expected_manifest["job_id"])
        if sha256_json(actual_manifest) != sha256_json(expected_manifest):
            errors.append(
                "database manifest differs from the normalized source manifest "
                f"(expected={sha256_json(expected_manifest)}, actual={sha256_json(actual_manifest)})"
            )
        try:
            revision = self.repository.get_current_artifact_revision(
                tenant_id,
                expected_manifest["job_id"],
                domain="migration.snapshot",
            )
        except RepositoryNotFound:
            return _ShadowResult(False, bool(errors), tuple(errors + ["migration snapshot is missing"]), 0, 0)
        if revision["revision_id"] != expected_revision:
            errors.append(
                "current migration revision differs from the captured source inventory "
                f"(expected={expected_revision}, actual={revision['revision_id']})"
            )
        expected = {item.logical_name: item for item in inspection.artifacts}
        actual = {item["logical_name"]: item for item in revision["artifacts"]}
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            errors.append(
                "database artifact names differ from the source snapshot "
                f"(missing={missing}, extra={extra})"
            )
        for name, source in expected.items():
            blob = actual.get(name)
            if blob is None:
                continue
            if blob["size_bytes"] != source.size_bytes or blob["sha256"] != source.sha256:
                errors.append(f"database artifact metadata mismatch: {name}")
                continue
            try:
                metadata = self.artifacts.object_store.head(blob["object_key"])
                stream_size, stream_sha = self._stream_digest(
                    self.artifacts.object_store.open(blob["object_key"])
                )
            except Exception as exc:
                errors.append(f"object verification failed for {name}: {exc}")
                continue
            if (
                metadata.size_bytes != source.size_bytes
                or metadata.sha256 != source.sha256
                or stream_size != source.size_bytes
                or stream_sha != source.sha256
            ):
                errors.append(f"object bytes mismatch: {name}")
                continue
            object_verified += 1
        return _ShadowResult(
            passed=not errors,
            hash_mismatch=bool(errors),
            errors=tuple(errors),
            database_artifact_count=len(actual),
            object_verified_count=object_verified,
        )

    @staticmethod
    def _apply_shadow_result(
        candidate: ImportCandidate,
        shadow: _ShadowResult,
        *,
        success_action: str,
    ) -> None:
        candidate.database_artifact_count = shadow.database_artifact_count
        candidate.object_verified_count = shadow.object_verified_count
        candidate.hash_mismatch = candidate.hash_mismatch or shadow.hash_mismatch
        if shadow.passed:
            candidate.action = success_action
            candidate.shadow_status = "passed"
            return
        candidate.valid = False
        candidate.action = "failed"
        candidate.shadow_status = "blocked"
        candidate.errors.extend(shadow.errors)

    @staticmethod
    def _normalize_manifest(manifest: dict[str, Any], directory_name: str) -> dict[str, Any]:
        normalized = copy.deepcopy(manifest)
        for transient in (
            "row_version",
            "snapshot_sequence",
            "database_manifest_sha256",
            "phase_c_snapshot",
            "deleted_at",
            "purge_after",
            "pinned",
            "legal_hold",
        ):
            normalized.pop(transient, None)
        normalized["manifest_version"] = 2
        normalized["job_id"] = str(normalized.get("job_id") or directory_name)
        normalized["project_name"] = str(normalized.get("project_name") or normalized["job_id"])
        normalized["status"] = str(normalized.get("status") or "created")
        normalized["stage"] = str(normalized.get("stage") or "created")
        normalized["input_mode"] = str(normalized.get("input_mode") or "project")
        normalized["approval_mode"] = str(normalized.get("approval_mode") or "editorial")
        normalized.setdefault("model_routes", {})
        normalized.setdefault("budget", {"currency": "USD", "limit_micros": None, "spent_micros": 0})
        return normalized

    @classmethod
    def _scan_job_files(cls, job_root: Path) -> tuple[list[_FileFact], list[_FileFact]]:
        if job_root.is_symlink():
            raise ValueError("job directory must not be a symbolic link")
        all_files: list[_FileFact] = []
        migratable: list[_FileFact] = []
        for path in sorted(job_root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"symbolic links are forbidden: {path.relative_to(job_root)}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError(f"special files are forbidden: {path.relative_to(job_root)}")
            before = path.stat()
            digest = sha256_file(path)
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise ValueError(f"file changed while being inspected: {path.relative_to(job_root)}")
            relative = path.relative_to(job_root).as_posix()
            fact = _FileFact(relative, path, after.st_size, digest)
            all_files.append(fact)
            if cls._is_migratable(relative):
                migratable.append(fact)
        return all_files, migratable

    @staticmethod
    def _is_migratable(relative_name: str) -> bool:
        relative = PurePosixPath(relative_name)
        if relative.name in SKIP_NAMES:
            return False
        if relative.name.startswith(".") and relative.name.endswith(".lock"):
            return False
        if any(part in SKIP_PARTS or part.startswith(".env") for part in relative.parts):
            return False
        return True

    @classmethod
    def _source_snapshot(cls, job_root: Path) -> str:
        all_files, _ = cls._scan_job_files(job_root)
        return cls._inventory_sha256(all_files)

    @staticmethod
    def _inventory_sha256(files: list[_FileFact] | tuple[_FileFact, ...]) -> str:
        return sha256_json(
            [
                {
                    "logical_name": item.logical_name,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                }
                for item in files
            ]
        )

    @classmethod
    def _revision_id(cls, job_id: str, files: tuple[_FileFact, ...]) -> str:
        seed = sha256_json(
            {
                "job_id": job_id,
                "inventory": [
                    {
                        "logical_name": item.logical_name,
                        "size_bytes": item.size_bytes,
                        "sha256": item.sha256,
                    }
                    for item in files
                ],
            }
        )
        return f"rev_migration_{seed[:20]}"

    @staticmethod
    def _safe_child(root: Path, logical_name: str) -> Path | None:
        if not logical_name or logical_name.startswith("/") or "\\" in logical_name or "\x00" in logical_name:
            return None
        relative = PurePosixPath(logical_name)
        if any(part in {"", ".", ".."} for part in relative.parts):
            return None
        root = root.resolve()
        candidate = (root / relative.as_posix()).resolve()
        if root not in candidate.parents:
            return None
        return candidate

    @staticmethod
    def _stream_digest(stream: BinaryIO) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        return size, digest.hexdigest()
