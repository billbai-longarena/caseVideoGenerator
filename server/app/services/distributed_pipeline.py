from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Mapping

from server.app.core.config import Settings
from server.app.core.errors import AppError
from server.app.models.job import utc_now_iso
from server.app.persistence.artifact_commit import (
    ArtifactCommitError,
    ArtifactCommitService,
    ArtifactSource,
)
from server.app.persistence.object_store import (
    ObjectStore,
    ObjectStoreError,
    validate_object_key,
)
from server.app.persistence.repository import (
    ArtifactBundleRegistration,
    ModelRunRegistration,
    PhaseCRepository,
    RepositoryError,
    RepositoryNotFound,
    sha256_json,
)
from server.app.services.model_gateway import ModelGateway
from server.app.services.pipeline import CaseVideoPipeline, V2_STAGES
from server.app.services.render_runner import IsolatedRenderRunner, RenderIsolationError
from server.app.services.revisions import RevisionService
from server.app.services.source_ingestion import SourceIngestion
from server.app.services.stage_graph import STAGE_INDEX, next_stage_name, stage_definition
from server.app.services.storage import JobStorage, StorageError, atomic_write_json, sha256_file
from server.app.services.streams import StageExecutionError, StageExecutionResult, StageMessage
from server.app.services.uploads import ALLOWED_EXTENSIONS, UploadStorage, safe_upload_name


_DATABASE_ONLY_MANIFEST_FIELDS = frozenset(
    {"row_version", "snapshot_sequence", "database_manifest_sha256", "deleted_at"}
)
_REVISION_DOMAINS = {
    "case_model": "case-model",
    "editorial": "editorial",
    "visual_plan": "visual-plan",
}
_PROJECT_FILES_BY_DOMAIN = {
    "case-model": frozenset({"case_model.json"}),
    "editorial": frozenset({"title.txt", "narration.txt", "review.json"}),
    "visual-plan": frozenset(
        {"storyboard_plan.json", "rich_storyboard.json", "image_prompts.json", "readiness.json"}
    ),
}
_TERMINAL_MODEL_STATUSES = frozenset({"succeeded", "reused", "failed"})
_EXCLUDED_WORKSPACE_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".env.local",
        ".env.production",
        ".manifest.lock",
        ".events.lock",
        ".model-runs.lock",
        ".case-video.lock",
    }
)
_SAFE_REVISION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")


class DistributedPipelineError(RuntimeError):
    """Safe execution error for a single distributed pipeline stage."""


@dataclass
class _MaterializationBudget:
    max_files: int
    max_bytes: int
    files: int = 0
    bytes: int = 0

    def reserve(self, *, size_bytes: int) -> None:
        if size_bytes < 0:
            raise DistributedPipelineError("artifact size cannot be negative")
        if self.files + 1 > self.max_files:
            raise DistributedPipelineError("artifact bundle exceeds the configured file limit")
        if self.bytes + size_bytes > self.max_bytes:
            raise DistributedPipelineError("artifact bundle exceeds the configured expansion limit")
        self.files += 1
        self.bytes += size_bytes


def _safe_destination(root: Path, logical_name: str) -> Path:
    normalized = validate_object_key(logical_name)
    relative = PurePosixPath(normalized)
    destination = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    resolved_destination = destination.resolve()
    if resolved_destination != resolved_root and resolved_root not in resolved_destination.parents:
        raise DistributedPipelineError("artifact path escapes the worker workspace")
    return destination


def _copy_object(
    object_store: ObjectStore,
    *,
    object_key: str,
    destination: Path,
    expected_sha256: str | None,
    expected_size: int | None,
    budget: _MaterializationBudget,
) -> None:
    metadata = object_store.head(object_key)
    if expected_size is not None and metadata.size_bytes != int(expected_size):
        raise DistributedPipelineError("object size does not match authoritative metadata")
    if expected_sha256 and metadata.sha256 != expected_sha256:
        raise DistributedPipelineError("object checksum does not match authoritative metadata")
    budget.reserve(size_bytes=metadata.size_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with object_store.open(object_key) as source, tempfile.NamedTemporaryFile(
        "wb", dir=str(destination.parent), delete=False
    ) as target:
        temporary = Path(target.name)
        try:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > metadata.size_bytes:
                    raise DistributedPipelineError("object stream exceeds authoritative size")
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    if size != metadata.size_bytes or digest.hexdigest() != metadata.sha256:
        temporary.unlink(missing_ok=True)
        raise DistributedPipelineError("object stream failed checksum verification")
    os.replace(temporary, destination)


def _terminal_model_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DistributedPipelineError("model provenance log contains invalid JSON") from exc
            run_id = record.get("run_id")
            status = record.get("status")
            if isinstance(run_id, str) and status in _TERMINAL_MODEL_STATUSES:
                records[run_id] = record
    return records


class DistributedStageExecutor:
    """Rebuild and execute exactly one immutable pipeline stage.

    PostgreSQL and object storage are authoritative. The local filesystem is a
    disposable compatibility layer for the existing JSON-driven production
    pipeline and is deleted after each stage attempt.
    """

    def __init__(
        self,
        settings: Settings,
        repository: PhaseCRepository,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store
        self.artifacts = ArtifactCommitService(repository, object_store)
        self.settings.worker_workspace_root.mkdir(parents=True, exist_ok=True)

    def __call__(
        self,
        message: StageMessage,
        claim: Mapping[str, Any],
    ) -> StageExecutionResult:
        try:
            return self._execute(message, claim)
        except StageExecutionError:
            raise
        except AppError as exc:
            raise StageExecutionError(exc.code, exc.message, retryable=exc.retryable) from exc
        except RenderIsolationError as exc:
            raise StageExecutionError("render_isolation_failed", str(exc), retryable=True) from exc
        except RepositoryNotFound as exc:
            raise StageExecutionError("not_found", str(exc), retryable=False) from exc
        except RepositoryError as exc:
            raise StageExecutionError(getattr(exc, "code", "repository_error"), str(exc), retryable=True) from exc
        except (ObjectStoreError, ArtifactCommitError, StorageError, OSError) as exc:
            raise StageExecutionError("artifact_materialization_failed", str(exc), retryable=True) from exc
        except (DistributedPipelineError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise StageExecutionError("artifact_corrupt", str(exc), retryable=False) from exc

    def _execute(
        self,
        message: StageMessage,
        claim: Mapping[str, Any],
    ) -> StageExecutionResult:
        self._validate_claim(message, claim)
        stage = stage_definition(str(claim["stage"]))
        index = STAGE_INDEX[stage.name]
        with tempfile.TemporaryDirectory(
            prefix=f"{message.stage_run_id}-",
            dir=str(self.settings.worker_workspace_root),
        ) as workspace_name:
            workspace = Path(workspace_name)
            local_settings = replace(
                self.settings,
                data_root=workspace / "jobs",
                render_workspace_root=workspace / "render",
            )
            storage = JobStorage(local_settings)
            self._create_job_layout(storage, message.job_id)
            budget = _MaterializationBudget(
                max_files=self.settings.max_archive_files,
                max_bytes=self.settings.max_archive_expansion_bytes,
            )
            manifest = copy.deepcopy(self.repository.get_job(message.tenant_id, message.job_id))
            self._bind_model_revision_request(manifest, claim)
            self._restore_current_workspace(message, storage, budget)
            self._write_authoritative_manifest(storage, message.job_id, manifest)
            self._restore_inputs(message, storage, budget)
            self._restore_current_revisions(message, storage, manifest, budget)

            before_revisions = self._revision_names(storage, message.job_id)
            before_models = set(_terminal_model_records(storage.model_runs_path(message.job_id)))

            gateway = ModelGateway(local_settings, storage)
            revisions = RevisionService(
                storage,
                gateway,
                revision_namespace=self._revision_namespace(message.job_id),
            )
            uploads = UploadStorage(local_settings)
            pipeline = CaseVideoPipeline(
                local_settings,
                storage,
                model_gateway=gateway,
                revisions=revisions,
                ingestion=SourceIngestion(local_settings, storage, uploads),
                render_runner=IsolatedRenderRunner(local_settings),
            )
            paused = pipeline._run_v2_stage(
                message.job_id,
                stage,
                index + 1,
                len(V2_STAGES),
                force=True,
            )
            if stage.name == V2_STAGES[-1].name and not paused:
                pipeline._complete_job(message.job_id)

            local_manifest = storage.read_manifest(message.job_id)
            bundles = self._stage_artifact_bundles(
                message,
                storage,
                before_revisions=before_revisions,
            )
            model_runs = self._new_model_registrations(
                storage.model_runs_path(message.job_id),
                before_models=before_models,
            )
            output_path = storage.job_root(message.job_id) / "stage-runs" / stage.name / "output.json"
            if not output_path.is_file():
                raise DistributedPipelineError("stage did not produce its required output record")

            next_name = None if paused else next_stage_name(stage.name)
            next_input_hash = None
            if next_name is not None:
                next_definition = stage_definition(next_name)
                next_input_hash = pipeline._v2_stage_input_hash(
                    message.job_id,
                    next_definition,
                    STAGE_INDEX[next_name] + 1,
                )
            return StageExecutionResult(
                output_hash=sha256_file(output_path),
                manifest=local_manifest,
                paid_result_key=self._paid_result_key(model_runs),
                next_stage=next_name,
                next_input_hash=next_input_hash,
                next_route_snapshot_hash=(
                    sha256_json(local_manifest.get("model_routes", {})) if next_name else None
                ),
                next_config_snapshot_hash=(
                    self._next_config_hash(local_manifest, next_name) if next_name else None
                ),
                next_priority=message.priority,
                artifact_bundles=tuple(bundles),
                model_runs=tuple(model_runs),
            )

    @staticmethod
    def _validate_claim(message: StageMessage, claim: Mapping[str, Any]) -> None:
        checks = (
            (claim.get("tenant_id"), message.tenant_id, "tenant_id"),
            (claim.get("job_id"), message.job_id, "job_id"),
            (claim.get("stage_run_id"), message.stage_run_id, "stage_run_id"),
        )
        for actual, expected, field in checks:
            if actual != expected:
                raise DistributedPipelineError(f"authoritative claim {field} mismatch")
        stage_definition(str(claim.get("stage", "")))

    @staticmethod
    def _bind_model_revision_request(
        manifest: dict[str, Any],
        claim: Mapping[str, Any],
    ) -> None:
        requests = manifest.get("model_revision_requests")
        if not isinstance(requests, dict):
            return
        stage = str(claim.get("stage") or "")
        input_hash = str(claim.get("input_hash") or "")
        matches = [
            (request_id, record)
            for request_id, record in requests.items()
            if isinstance(record, dict)
            and record.get("stage") == stage
            and record.get("request_hash") == input_hash
        ]
        if not matches:
            return
        if len(matches) > 1:
            raise DistributedPipelineError("multiple model revision requests match the same stage input")
        request_id, record = matches[0]
        now = utc_now_iso()
        record.update(
            {
                "status": "running",
                "stage_run_id": claim.get("stage_run_id"),
                "started_at": record.get("started_at") or now,
                "updated_at": now,
            }
        )
        manifest["active_model_revision_request_id"] = request_id

    @staticmethod
    def _create_job_layout(storage: JobStorage, job_id: str) -> None:
        root = storage.job_root(job_id)
        for relative in (
            "source",
            "logs",
            "revisions/case-model",
            "revisions/editorial",
            "revisions/visual-plan",
            "stage-runs",
            "project",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_authoritative_manifest(
        storage: JobStorage,
        job_id: str,
        manifest: Mapping[str, Any],
    ) -> None:
        payload = {
            key: value
            for key, value in manifest.items()
            if key not in _DATABASE_ONLY_MANIFEST_FIELDS
        }
        storage.write_manifest(job_id, payload)

    def _restore_current_workspace(
        self,
        message: StageMessage,
        storage: JobStorage,
        budget: _MaterializationBudget,
    ) -> None:
        try:
            revision = self.repository.get_current_artifact_revision(
                message.tenant_id,
                message.job_id,
                domain="workspace",
            )
        except RepositoryNotFound:
            return
        self._materialize_revision(
            revision,
            root=storage.job_root(message.job_id),
            budget=budget,
        )

    def _restore_inputs(
        self,
        message: StageMessage,
        storage: JobStorage,
        budget: _MaterializationBudget,
    ) -> None:
        job_root = storage.job_root(message.job_id)
        for item in self.repository.list_job_inputs(message.tenant_id, message.job_id):
            object_key = item.get("object_key")
            if not object_key:
                raise DistributedPipelineError("job input is missing its immutable object key")
            if item.get("kind") == "structured":
                destination = job_root / "source" / "structured_input.json"
            elif item.get("kind") == "upload":
                upload_id = str(item.get("upload_id") or "")
                if not upload_id.startswith("upl_") or not upload_id.replace("_", "").isalnum():
                    raise DistributedPipelineError("job input contains an invalid upload identifier")
                destination = storage.settings.data_root / "_uploads" / upload_id / "payload.bin"
            else:
                raise DistributedPipelineError(f"unsupported distributed input kind: {item.get('kind')}")
            _copy_object(
                self.object_store,
                object_key=str(object_key),
                destination=destination,
                expected_sha256=item.get("sha256"),
                expected_size=item.get("size_bytes"),
                budget=budget,
            )
            if item.get("kind") == "upload":
                self._write_upload_metadata(storage, message.job_id, item)

    @staticmethod
    def _write_upload_metadata(
        storage: JobStorage,
        job_id: str,
        item: Mapping[str, Any],
    ) -> None:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        upload_id = str(item["upload_id"])
        filename = str(metadata.get("filename") or f"source-{item['input_id']}.txt")
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise DistributedPipelineError("uploaded source has an unsupported extension")
        now = datetime.now(timezone.utc)
        detected = str(item.get("media_type") or "application/octet-stream")
        record = {
            "upload_id": upload_id,
            "filename": filename,
            "safe_name": safe_upload_name(filename),
            "suffix": suffix,
            "declared_size_bytes": int(item.get("size_bytes") or 0),
            "size_bytes": int(item.get("size_bytes") or 0),
            "declared_media_type": detected,
            "detected_media_type": detected,
            "declared_sha256": item.get("sha256"),
            "sha256": item.get("sha256"),
            "status": "complete",
            "max_size_bytes": storage.settings.max_upload_bytes,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(days=3650)).isoformat().replace("+00:00", "Z"),
            "completed_at": now.isoformat().replace("+00:00", "Z"),
            "bound_job_id": job_id,
            "bound_at": now.isoformat().replace("+00:00", "Z"),
        }
        atomic_write_json(storage.settings.data_root / "_uploads" / upload_id / "metadata.json", record)

    def _restore_current_revisions(
        self,
        message: StageMessage,
        storage: JobStorage,
        manifest: Mapping[str, Any],
        budget: _MaterializationBudget,
    ) -> None:
        current = manifest.get("current_revisions")
        if not isinstance(current, Mapping):
            return
        for manifest_key, domain in _REVISION_DOMAINS.items():
            revision_id = current.get(manifest_key)
            if not revision_id:
                continue
            revision = self.repository.get_artifact_revision(message.tenant_id, str(revision_id))
            if revision.get("job_id") != message.job_id or revision.get("domain") != domain:
                raise DistributedPipelineError("current revision pointer crosses a job or domain boundary")
            revision_root = storage.job_root(message.job_id) / "revisions" / domain / str(revision_id)
            self._materialize_revision(revision, root=revision_root, budget=budget)
            for artifact in revision.get("artifacts", []):
                logical_name = str(artifact.get("logical_name") or "")
                if logical_name in _PROJECT_FILES_BY_DOMAIN[domain]:
                    source = _safe_destination(revision_root, logical_name)
                    destination = storage.project_root(message.job_id) / logical_name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read_bytes())

    def _materialize_revision(
        self,
        revision: Mapping[str, Any],
        *,
        root: Path,
        budget: _MaterializationBudget,
    ) -> None:
        for artifact in revision.get("artifacts", []):
            logical_name = str(artifact.get("logical_name") or "")
            destination = _safe_destination(root, logical_name)
            _copy_object(
                self.object_store,
                object_key=str(artifact["object_key"]),
                destination=destination,
                expected_sha256=artifact.get("sha256"),
                expected_size=artifact.get("size_bytes"),
                budget=budget,
            )

    @staticmethod
    def _revision_namespace(job_id: str) -> str:
        return f"job-{hashlib.sha256(job_id.encode('utf-8')).hexdigest()[:12]}"

    @staticmethod
    def _revision_names(storage: JobStorage, job_id: str) -> dict[str, set[str]]:
        root = storage.job_root(job_id) / "revisions"
        return {
            domain: {item.name for item in (root / domain).iterdir() if item.is_dir()}
            for domain in _PROJECT_FILES_BY_DOMAIN
        }

    def _stage_artifact_bundles(
        self,
        message: StageMessage,
        storage: JobStorage,
        *,
        before_revisions: Mapping[str, set[str]],
    ) -> list[ArtifactBundleRegistration]:
        bundles: list[ArtifactBundleRegistration] = []
        root = storage.job_root(message.job_id)
        for domain in _PROJECT_FILES_BY_DOMAIN:
            domain_root = root / "revisions" / domain
            new_ids = sorted(
                (item.name for item in domain_root.iterdir() if item.is_dir()),
                key=lambda value: self._revision_sort_key(domain_root / value),
            )
            for revision_id in new_ids:
                if revision_id in before_revisions.get(domain, set()):
                    continue
                if not _SAFE_REVISION_ID.fullmatch(revision_id):
                    raise DistributedPipelineError("pipeline emitted an unsafe revision identifier")
                revision_root = domain_root / revision_id
                metadata = self._read_revision_metadata(revision_root)
                sources = self._artifact_sources(revision_root)
                bundles.append(
                    self.artifacts.stage_bundle(
                        tenant_id=message.tenant_id,
                        job_id=message.job_id,
                        domain=domain,
                        revision_id=revision_id,
                        parent_id=metadata.get("parent_revision"),
                        sources=sources,
                        created_by=str(metadata.get("actor") or metadata.get("author_type") or "worker"),
                        make_current=True,
                    )
                )

        workspace_revision_id = f"workspace-{message.stage_run_id}"
        if not _SAFE_REVISION_ID.fullmatch(workspace_revision_id):
            raise DistributedPipelineError("stage run identifier cannot form a safe workspace revision")
        workspace_sources = self._workspace_sources(root)
        try:
            parent = self.repository.get_current_artifact_revision(
                message.tenant_id,
                message.job_id,
                domain="workspace",
            )["revision_id"]
        except RepositoryNotFound:
            parent = None
        bundles.append(
            self.artifacts.stage_bundle(
                tenant_id=message.tenant_id,
                job_id=message.job_id,
                domain="workspace",
                revision_id=workspace_revision_id,
                parent_id=parent,
                sources=workspace_sources,
                created_by="distributed-worker",
                make_current=True,
            )
        )
        return bundles

    @staticmethod
    def _read_revision_metadata(revision_root: Path) -> dict[str, Any]:
        path = revision_root / "metadata.json"
        if not path.is_file():
            raise DistributedPipelineError("revision is missing metadata.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise DistributedPipelineError("revision metadata must be an object")
        return payload

    @staticmethod
    def _revision_sort_key(revision_root: Path) -> tuple[int, str]:
        try:
            payload = json.loads((revision_root / "metadata.json").read_text(encoding="utf-8"))
            return int(payload.get("revision_number", 0)), revision_root.name
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0, revision_root.name

    def _artifact_sources(self, root: Path) -> list[ArtifactSource]:
        sources: list[ArtifactSource] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise DistributedPipelineError("symbolic links are forbidden in stage artifacts")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            validate_object_key(relative)
            sources.append(
                ArtifactSource(
                    logical_name=relative,
                    path=path,
                    media_type=mimetypes.guess_type(path.name)[0],
                )
            )
        if not sources:
            raise DistributedPipelineError("revision contains no artifacts")
        return sources

    def _workspace_sources(self, job_root: Path) -> list[ArtifactSource]:
        sources: list[ArtifactSource] = []
        total_size = 0
        for path in sorted(job_root.rglob("*")):
            if path.is_symlink():
                raise DistributedPipelineError("symbolic links are forbidden in the worker workspace")
            if not path.is_file():
                continue
            relative = path.relative_to(job_root)
            if relative.parts and relative.parts[0] == "revisions":
                continue
            if any(part == "__pycache__" for part in relative.parts):
                continue
            if path.name in _EXCLUDED_WORKSPACE_NAMES or path.name.startswith(".env."):
                continue
            logical_name = validate_object_key(relative.as_posix())
            total_size += path.stat().st_size
            if len(sources) + 1 > self.settings.max_archive_files:
                raise DistributedPipelineError("workspace exceeds the configured file limit")
            if total_size > self.settings.max_archive_expansion_bytes:
                raise DistributedPipelineError("workspace exceeds the configured size limit")
            sources.append(
                ArtifactSource(
                    logical_name=logical_name,
                    path=path,
                    media_type=mimetypes.guess_type(path.name)[0],
                )
            )
        if not sources:
            raise DistributedPipelineError("stage workspace contains no commit-ready artifacts")
        return sources

    @staticmethod
    def _new_model_registrations(
        path: Path,
        *,
        before_models: set[str],
    ) -> list[ModelRunRegistration]:
        registrations: list[ModelRunRegistration] = []
        for run_id, record in sorted(_terminal_model_records(path).items()):
            if run_id in before_models or record.get("status") not in {"succeeded", "reused"}:
                continue
            output_schema = record.get("output_schema")
            schema_version = (
                str(output_schema.get("version"))
                if isinstance(output_schema, Mapping) and output_schema.get("version")
                else "unknown"
            )
            usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
            cost_micros = usage.get("cost_micros", 0)
            if not isinstance(cost_micros, int) or cost_micros < 0:
                cost_micros = 0
            registrations.append(
                ModelRunRegistration(
                    id=run_id,
                    task=str(record.get("task") or "unknown"),
                    provider=str(record.get("provider") or "unknown"),
                    model=str(record.get("model") or "unknown"),
                    route_snapshot={
                        "provider": record.get("provider"),
                        "model": record.get("model"),
                        "deployment": record.get("deployment"),
                        "transport": record.get("transport"),
                        "route_family": record.get("route_family"),
                    },
                    prompt_version=str(record.get("prompt_version") or "unknown"),
                    schema_version=schema_version,
                    provider_call_id=(
                        str(record["provider_call_id"])
                        if record.get("provider_call_id") is not None
                        else None
                    ),
                    usage=usage,
                    cost_micros=cost_micros,
                    status=str(record.get("status") or "succeeded"),
                )
            )
        return registrations

    @staticmethod
    def _paid_result_key(model_runs: Iterable[ModelRunRegistration]) -> str | None:
        paid = [item.provider_call_id for item in model_runs if item.provider_call_id]
        return paid[-1] if paid else None

    @staticmethod
    def _next_config_hash(manifest: Mapping[str, Any], next_stage: str) -> str:
        return sha256_json(
            {
                "manifest_version": manifest.get("manifest_version"),
                "contract_versions": manifest.get("contract_versions", {}),
                "prompt_pins": manifest.get("prompt_pins", {}),
                "stage": next_stage,
            }
        )


__all__ = ["DistributedStageExecutor", "DistributedPipelineError", "_safe_destination"]
