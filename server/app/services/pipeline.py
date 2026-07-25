from __future__ import annotations

import base64
import copy
import io
import json
import os
import re
import signal
import subprocess
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from server.app.core.config import Settings
from server.app.core.errors import AppError
from server.app.models.job import JobStatus, utc_now_iso
from server.app.services.contracts import canonical_json
from server.app.services.intent_frames import intent_frame_description, select_intent_frames
from server.app.services.model_gateway import ModelGateway
from server.app.services.render_runner import IsolatedRenderRunner, RenderIsolationError
from server.app.services.revisions import PROGRAM_CLOSER, PROGRAM_OPENER, RevisionService
from server.app.services.source_ingestion import SourceIngestion
from server.app.services.stage_graph import PIPELINE_STAGES, StageDefinition
from server.app.services.storage import (
    JobStorage,
    StorageError,
    atomic_write_json,
    atomic_write_text,
    sha256_file,
    sha256_text,
)
from server.app.services.uploads import UploadStorage
from server.app.services.visual_adapter import build_rich_storyboard, prompt_image_path


@dataclass(frozen=True)
class PipelineStage:
    name: str
    display: str
    command: tuple[str, ...] | None
    input_files: tuple[str, ...]


@dataclass
class StageResult:
    output: dict[str, Any] = field(default_factory=dict)
    paused: bool = False
    display_status: str | None = None
    next_action: str | None = None
    can_approve: bool = False


class PipelineCanceled(RuntimeError):
    pass


V2Stage = StageDefinition
V2_STAGES: tuple[StageDefinition, ...] = PIPELINE_STAGES


_STAGE_PROMPT_TASKS: dict[str, tuple[str, ...]] = {
    "case.model": ("source.classify", "case.extract", "case.model"),
    "editorial.compose": ("narration.compose",),
    "editorial.review": ("editorial.review",),
    "editorial.rewrite": ("narration.rewrite", "editorial.review"),
    "visual.plan": ("remotion.plan",),
    "visual.repair": ("remotion.repair",),
    "assets.generate": ("image_prompt.refine",),
    "visual.intent-review": ("remotion.frame-review", "remotion.repair"),
    "delivery.finalize": ("delivery.summarize",),
}


class CaseVideoPipeline:
    def __init__(
        self,
        settings: Settings,
        storage: JobStorage,
        *,
        model_gateway: ModelGateway | None = None,
        revisions: RevisionService | None = None,
        ingestion: SourceIngestion | None = None,
        render_runner: IsolatedRenderRunner | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.model_gateway = model_gateway or ModelGateway(settings, storage)
        self.revisions = revisions or RevisionService(storage, self.model_gateway)
        self.uploads = UploadStorage(settings)
        self.ingestion = ingestion or SourceIngestion(settings, storage, self.uploads)
        self.render_runner = render_runner

    # Phase A compatibility path. Existing project-mode jobs intentionally keep
    # their original seven public stage names and command behavior.
    def stages(self, project_root: Path) -> list[PipelineStage]:
        return [
            PipelineStage(
                "source_ready",
                "检查项目源文件",
                None,
                ("title.txt", "narration.txt", "storyboard_plan.json", "rich_storyboard.json"),
            ),
            PipelineStage(
                "tts_ready",
                "生成 Azure 旁白与时间轴",
                (
                    str(self.settings.repo_root / "scripts" / "case-video"),
                    "tts",
                    str(project_root),
                    "--gender",
                    "female",
                    "--single-voice",
                    "--force",
                ),
                ("title.txt", "narration.txt"),
            ),
            PipelineStage(
                "project_checked",
                "校验项目合同",
                (str(self.settings.repo_root / "scripts" / "case-video"), "check", str(project_root)),
                ("title.txt", "narration.timeline.json", "rich_storyboard.json", "storyboard_plan.json"),
            ),
            PipelineStage(
                "render_ready",
                "执行渲染 readiness",
                (
                    str(self.settings.repo_root / "scripts" / "case-video"),
                    "ready",
                    str(project_root),
                    "--stage",
                    "render",
                ),
                ("title.txt", "narration.timeline.json", "rich_storyboard.json"),
            ),
            PipelineStage(
                "typechecked",
                "Remotion typecheck",
                (str(self.settings.repo_root / "scripts" / "case-video"), "typecheck", str(project_root)),
                ("rich_storyboard.json",),
            ),
            PipelineStage(
                "rendering",
                "Remotion 渲染",
                (str(self.settings.repo_root / "scripts" / "case-video"), "render", str(project_root)),
                ("title.txt", "narration.timeline.json", "rich_storyboard.json"),
            ),
            PipelineStage(
                "qa",
                "ffprobe QA",
                (str(self.settings.repo_root / "scripts" / "case-video"), "qa", str(project_root)),
                ("video/case_video.mp4", "narration.timeline.json"),
            ),
        ]

    def run(self, job_id: str, force: bool = False) -> dict[str, Any]:
        manifest = self.storage.read_manifest(job_id)
        if manifest.get("cancel_requested"):
            return self.storage.mark_canceled(job_id, manifest.get("stage", "created"))

        self._mark_job_started(job_id)
        try:
            if manifest.get("input_mode", "project") == "project":
                return self._run_legacy_project(job_id, force=force)
            return self._run_v2(job_id, force=force)
        except PipelineCanceled:
            stage = self.storage.read_manifest(job_id).get("stage", "canceling")
            return self.storage.mark_canceled(job_id, stage)
        except AppError as exc:
            stage = exc.stage or self.storage.read_manifest(job_id).get("stage", "unknown")
            self._mark_stage_failed(job_id, stage, exc.code, exc.message, retryable=exc.retryable)
            return self.storage.read_manifest(job_id)
        except (StorageError, subprocess.SubprocessError, OSError, RuntimeError, ValueError) as exc:
            stage = self.storage.read_manifest(job_id).get("stage", "unknown")
            self._mark_stage_failed(job_id, stage, "pipeline-stage-failed", str(exc), retryable=True)
            return self.storage.read_manifest(job_id)

    def _mark_job_started(self, job_id: str) -> None:
        manifest = self.storage.read_manifest(job_id)
        manifest.update(
            {
                "status": JobStatus.running.value,
                "display_status": "处理中",
                "can_cancel": True,
                "can_retry": False,
                "needs_action": False,
                "next_action": None,
                "last_heartbeat_at": utc_now_iso(),
            }
        )
        manifest.pop("error", None)
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(job_id, "job.started", manifest.get("stage"), "worker 已开始处理任务", {})

    def _run_legacy_project(self, job_id: str, force: bool) -> dict[str, Any]:
        project_root = self.storage.project_root(job_id)
        self.storage.validate_phase_a_project(project_root)
        stages = self.stages(project_root)
        for index, stage in enumerate(stages, start=1):
            self._check_cancel(job_id, stage.name)
            self._run_stage(job_id, stage, index, len(stages), force=force)
        return self._complete_job(job_id)

    def _run_v2(self, job_id: str, force: bool) -> dict[str, Any]:
        self.model_gateway.validate_required_routes()
        manifest = self.storage.read_manifest(job_id)
        stage_catalog = [
            {
                "index": index,
                "name": stage.name,
                "display": stage.display,
                "model_task": stage.model_task,
            }
            for index, stage in enumerate(V2_STAGES, start=1)
        ]
        if manifest.get("pipeline_stages") != stage_catalog:
            manifest["pipeline_stages"] = stage_catalog
            self.storage.write_manifest(job_id, manifest)
        for index, stage in enumerate(V2_STAGES, start=1):
            self._check_cancel(job_id, stage.name)
            paused = self._run_v2_stage(job_id, stage, index, len(V2_STAGES), force=force)
            if paused:
                return self.storage.read_manifest(job_id)
        return self._complete_job(job_id)

    def _run_v2_stage(
        self,
        job_id: str,
        stage: V2Stage,
        index: int,
        total: int,
        *,
        force: bool,
    ) -> bool:
        input_hash = self._v2_stage_input_hash(job_id, stage, index)
        manifest = self.storage.read_manifest(job_id)
        previous = manifest.get("stage_runs", {}).get(stage.name)
        if previous and previous.get("status") == "succeeded" and previous.get("input_hash") == input_hash and not force:
            self.storage.append_event(
                job_id,
                "stage.skipped",
                stage.name,
                f"{stage.display} 已有有效产物，跳过",
                {"input_hash": input_hash},
            )
            return False

        started_at = utc_now_iso()
        run_count = int(previous.get("run_count", 0)) + 1 if isinstance(previous, dict) else 1
        manifest.update(
            {
                "status": JobStatus.running.value,
                "display_status": stage.display,
                "stage": stage.name,
                "overall_progress": round((index - 1) / total, 4),
                "stage_progress": {
                    "stage": stage.name,
                    "status": "running",
                    "message": stage.display,
                    "started_at": started_at,
                },
                "needs_action": False,
                "next_action": None,
                "can_approve": False,
                "last_heartbeat_at": started_at,
            }
        )
        manifest.setdefault("stage_runs", {})[stage.name] = {
            "stage": stage.name,
            "display": stage.display,
            "status": "running",
            "started_at": started_at,
            "input_hash": input_hash,
            "run_count": run_count,
            "model_task": stage.model_task,
            "dry_run": self.settings.dry_run,
        }
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(
            job_id,
            "stage.started",
            stage.name,
            stage.display,
            {"dry_run": self.settings.dry_run, "run_count": run_count},
        )

        handler: Callable[[str], StageResult] = getattr(self, stage.handler)
        result = handler(job_id)
        output_path = self._stage_output_path(job_id, stage.name)
        atomic_write_json(output_path, result.output)
        output_hash = sha256_file(output_path)
        if result.paused:
            self._mark_stage_waiting(job_id, stage, index, total, input_hash, output_hash, result)
            return True
        self._mark_stage_succeeded(job_id, stage, index, total, input_hash, output_hash)
        return False

    def _v2_stage_input_hash(self, job_id: str, stage: V2Stage, index: int) -> str:
        manifest = self.storage.read_manifest(job_id)
        previous_run: dict[str, Any] | None = None
        if index > 1:
            previous_run = manifest.get("stage_runs", {}).get(V2_STAGES[index - 2].name)
        payload: dict[str, Any] = {
            "stage": stage.name,
            "input_mode": manifest.get("input_mode"),
            "project_name": manifest.get("project_name"),
            "approval_mode": manifest.get("approval_mode"),
            "target_duration_seconds": manifest.get("target_duration_seconds"),
            "program": manifest.get("program"),
            "previous_output_hash": previous_run.get("output_hash") if previous_run else None,
            "previous_status": previous_run.get("status") if previous_run else None,
            "prompt_pins": {
                task: manifest.get("prompt_pins", {}).get(task)
                for task in _STAGE_PROMPT_TASKS.get(stage.name, ())
            },
        }
        if stage.name == "ingest.validate":
            payload["inputs"] = manifest.get("inputs", {})
            structured = self.storage.job_root(job_id) / "source" / "structured_input.json"
            payload["structured_sha256"] = sha256_file(structured) if structured.is_file() else None
            upload_records: list[dict[str, Any]] = []
            for upload_id in manifest.get("inputs", {}).get("upload_ids", []):
                record = self.uploads.get(upload_id)
                upload_records.append(
                    {
                        "upload_id": upload_id,
                        "status": record.get("status"),
                        "size_bytes": record.get("size_bytes"),
                        "sha256": record.get("sha256"),
                        "suffix": record.get("suffix"),
                    }
                )
            payload["uploads"] = upload_records
        if stage.name == "visual.contract-approval":
            checkpoint = manifest.get("approval_checkpoints", {}).get("visual_contract")
            payload["contract_revision"] = checkpoint or manifest.get("current_revisions", {}).get("visual_plan")
            payload["contract_approved"] = checkpoint is not None
        elif stage.name in {"editorial.approval", "visual.approval"}:
            domain = "editorial" if stage.name.startswith("editorial") else "visual_plan"
            payload["current_revision"] = manifest.get("current_revisions", {}).get(domain)
            payload["approved_revision"] = manifest.get("approved_revisions", {}).get(domain)
            payload["review_decision"] = manifest.get("review_decisions", {}).get(domain)
        return sha256_text(canonical_json(payload))

    def _stage_output_path(self, job_id: str, stage_name: str) -> Path:
        return self.storage.job_root(job_id) / "stage-runs" / stage_name / "output.json"

    def _active_model_revision_request(
        self,
        job_id: str,
        expected_stage: str,
        expected_domain: str,
    ) -> dict[str, Any] | None:
        manifest = self.storage.read_manifest(job_id)
        request_id = manifest.get("active_model_revision_request_id")
        if not request_id:
            return None
        requests = manifest.get("model_revision_requests")
        if not isinstance(requests, dict):
            raise AppError("request_invalid", "active model revision request registry is missing")
        record = requests.get(str(request_id))
        if not isinstance(record, dict):
            raise AppError("request_invalid", "active model revision request is missing")
        if record.get("stage") != expected_stage or record.get("domain") != expected_domain:
            raise AppError("request_invalid", "active model revision request does not match this stage")
        return copy.deepcopy(record)

    def _finish_model_revision_request(
        self,
        job_id: str,
        request_id: str,
        *,
        outcome: str,
        result_revision: str,
    ) -> None:
        manifest = self.storage.read_manifest(job_id)
        requests = manifest.get("model_revision_requests")
        if not isinstance(requests, dict) or not isinstance(requests.get(request_id), dict):
            raise AppError("request_invalid", "active model revision request is missing")
        now = utc_now_iso()
        requests[request_id].update(
            {
                "status": "succeeded",
                "outcome": outcome,
                "result_revision": result_revision,
                "completed_at": now,
                "updated_at": now,
            }
        )
        if manifest.get("active_model_revision_request_id") == request_id:
            manifest.pop("active_model_revision_request_id", None)
        self.storage.write_manifest(job_id, manifest)

    def _mark_stage_succeeded(
        self,
        job_id: str,
        stage: V2Stage,
        index: int,
        total: int,
        input_hash: str,
        output_hash: str,
    ) -> None:
        manifest = self.storage.read_manifest(job_id)
        finished_at = utc_now_iso()
        run = manifest.setdefault("stage_runs", {}).setdefault(stage.name, {})
        run.update(
            {
                "status": "succeeded",
                "finished_at": finished_at,
                "input_hash": input_hash,
                "output_hash": output_hash,
                "output": self._stage_output_path(job_id, stage.name).relative_to(self.storage.job_root(job_id)).as_posix(),
                "returncode": 0,
            }
        )
        manifest.update(
            {
                "status": JobStatus.running.value,
                "display_status": stage.display,
                "stage": stage.name,
                "overall_progress": round(index / total, 4),
                "stage_progress": {
                    "stage": stage.name,
                    "status": "succeeded",
                    "message": f"{stage.display}完成",
                    "finished_at": finished_at,
                },
                "needs_action": False,
                "next_action": None,
                "can_approve": False,
                "can_cancel": True,
                "can_retry": False,
                "last_heartbeat_at": finished_at,
            }
        )
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(job_id, "stage.succeeded", stage.name, f"{stage.display}完成", {})

    def _mark_stage_waiting(
        self,
        job_id: str,
        stage: V2Stage,
        index: int,
        total: int,
        input_hash: str,
        output_hash: str,
        result: StageResult,
    ) -> None:
        manifest = self.storage.read_manifest(job_id)
        run = manifest.setdefault("stage_runs", {}).setdefault(stage.name, {})
        run.update(
            {
                "status": "waiting",
                "waiting_since": utc_now_iso(),
                "input_hash": input_hash,
                "output_hash": output_hash,
                "output": self._stage_output_path(job_id, stage.name).relative_to(self.storage.job_root(job_id)).as_posix(),
            }
        )
        manifest.update(
            {
                "status": JobStatus.waiting_approval.value,
                "display_status": result.display_status or stage.display,
                "stage": stage.name,
                "overall_progress": round((index - 1) / total, 4),
                "stage_progress": {
                    "stage": stage.name,
                    "status": "waiting",
                    "message": result.next_action or stage.display,
                },
                "needs_action": True,
                "next_action": result.next_action or "审核当前版本",
                "can_approve": result.can_approve,
                "can_cancel": True,
                "can_retry": False,
                "last_heartbeat_at": utc_now_iso(),
            }
        )
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(
            job_id,
            "stage.waiting",
            stage.name,
            manifest["display_status"],
            {"can_approve": result.can_approve},
        )

    def _mark_stage_failed(
        self,
        job_id: str,
        stage: str,
        error_code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        manifest = self.storage.read_manifest(job_id)
        run = manifest.setdefault("stage_runs", {}).setdefault(stage, {"stage": stage})
        run.update(
            {
                "status": "failed",
                "finished_at": utc_now_iso(),
                "error_code": error_code,
                "error_message": message,
                "retryable": retryable,
            }
        )
        self.storage.write_manifest(job_id, manifest)
        failed = self.storage.mark_failed(job_id, stage, error_code, message)
        failed["can_retry"] = retryable
        failed.setdefault("error", {})["retryable"] = retryable
        self.storage.write_manifest(job_id, failed)

    # ------------------------------------------------------------------
    # Full source/structured pipeline handlers

    def _stage_ingest_validate(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        mode = manifest.get("input_mode")
        if mode not in {"source", "structured"}:
            raise AppError("source_invalid", "18-stage pipeline requires source or structured input", stage="ingest.validate")
        upload_ids = list(manifest.get("inputs", {}).get("upload_ids", []))
        structured = self.storage.job_root(job_id) / "source" / "structured_input.json"
        if mode == "structured" and not structured.is_file():
            raise AppError("source_invalid", "structured input is missing", stage="ingest.validate")
        if mode == "source" and not upload_ids and not structured.is_file():
            raise AppError("source_invalid", "source job has no input material", stage="ingest.validate")
        uploads: list[dict[str, Any]] = []
        for upload_id in upload_ids:
            record = self.uploads.get(upload_id)
            if record.get("status") != "complete":
                raise AppError("upload_incomplete", f"upload is not complete: {upload_id}", stage="ingest.validate")
            self.uploads.verify_bytes(upload_id)
            uploads.append(
                {
                    "upload_id": upload_id,
                    "safe_name": record.get("safe_name"),
                    "size_bytes": record.get("size_bytes"),
                    "sha256": record.get("sha256"),
                    "media_type": record.get("detected_media_type"),
                }
            )
        return StageResult(
            {
                "version": "1",
                "input_mode": mode,
                "uploads": uploads,
                "has_structured_input": structured.is_file(),
                "validated_at": utc_now_iso(),
            }
        )

    def _stage_source_extract(self, job_id: str) -> StageResult:
        extracted = self.ingestion.ingest(job_id)
        return StageResult(
            {
                "version": "1",
                "source_count": len(extracted["source_manifest"]["files"]),
                "external_excerpt_chars": extracted["boundary"]["total_excerpt_chars"],
                "source_manifest_sha256": sha256_file(self.storage.job_root(job_id) / "source" / "source_manifest.json"),
                "case_inputs_sha256": sha256_file(self.storage.job_root(job_id) / "source" / "case_inputs.json"),
                "external_boundary_sha256": sha256_file(self.storage.job_root(job_id) / "source" / "external_boundary.json"),
            }
        )

    def _stage_case_model(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        case_inputs = self._read_json(self.storage.job_root(job_id) / "source" / "case_inputs.json", "case.model")
        boundary = self._read_json(self.storage.job_root(job_id) / "source" / "external_boundary.json", "case.model")
        excerpts = self._model_source_excerpts(boundary)
        base_context = {
            "project_name": manifest["project_name"],
            "program": manifest.get("program", "销售不复杂"),
            "case_inputs": case_inputs,
            "source_refs": [item["source_id"] for item in excerpts],
        }
        classification = self.model_gateway.run_json(
            "source.classify",
            "v1",
            {"task": "source.classify", "context": base_context, "source_excerpts": excerpts},
            job_id=job_id,
        )
        facts = self.model_gateway.run_json(
            "case.extract",
            "v1",
            {
                "task": "case.extract",
                "context": {**base_context, "classification": classification},
                "source_excerpts": excerpts,
            },
            job_id=job_id,
        )
        case_model = self.model_gateway.run_json(
            "case.model",
            "v1",
            {
                "task": "case.model",
                "context": {**base_context, "classification": classification, "fact_candidates": facts},
                "source_excerpts": excerpts,
            },
            job_id=job_id,
        )
        revision = self.revisions.create_case_model(
            job_id,
            case_model,
            change_summary="根据来源材料构建案例事实模型",
            actor="pipeline",
            input_hash=sha256_text(canonical_json({"classification": classification, "facts": facts})),
        )
        return StageResult(
            {
                "version": "1",
                "classification": classification,
                "fact_candidates": facts,
                "case_model": case_model,
                "revision": revision["metadata"]["revision_id"],
                "reused": revision.get("reused", False),
                "route": {"provider": "openai", "model": "gpt-5.5"},
            }
        )

    def _stage_editorial_compose(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        case_model = self._current_revision_files(job_id, "case-model")["case_model.json"]
        excerpts = self._model_source_excerpts(
            self._read_json(self.storage.job_root(job_id) / "source" / "external_boundary.json", "editorial.compose")
        )
        output = self.model_gateway.run_json(
            "narration.compose",
            "v1",
            {
                "task": "narration.compose",
                "context": {
                    "project_name": manifest["project_name"],
                    "program": manifest.get("program", "销售不复杂"),
                    "case_model": case_model,
                    "source_refs": case_model.get("source_refs", []),
                    "target_duration_seconds": manifest.get("target_duration_seconds") or {"min": 240, "max": 420},
                },
                "source_excerpts": excerpts,
                "constraints": {
                    "fixed_opener": PROGRAM_OPENER,
                    "fixed_closer": PROGRAM_CLOSER,
                    "spoken_language": "natural Chinese",
                    "prohibited_patterns": ["不是……而是……", "不是...而是..."],
                    "acronyms_contiguous": True,
                },
            },
            job_id=job_id,
        )
        revision = self.revisions.create_editorial(
            job_id,
            title=output["title"],
            narration=output["narration"],
            change_summary=output.get("change_summary", "生成标题与旁白初稿"),
            author_type="model",
            actor="azure-anthropic:salesnail-cs-46",
            input_hash=sha256_text(canonical_json(case_model)),
            enforce_concurrency=False,
        )
        return StageResult(
            {
                "version": "1",
                "revision": revision["metadata"]["revision_id"],
                "reused": revision.get("reused", False),
                "title": output["title"],
                "narration_chars": len(re.sub(r"\s+", "", output["narration"])),
                "route": {
                    "provider": "azure_anthropic",
                    "deployment": "salesnail-cs-46",
                    "transport": "anthropic_messages",
                },
            }
        )

    def _stage_editorial_lint(self, job_id: str) -> StageResult:
        current = self.revisions.current_review(job_id, "editorial")
        files = current["files"]
        review = self.revisions.review_editorial(
            job_id,
            str(files["title.txt"]).strip(),
            str(files["narration.txt"]).strip(),
        )
        return StageResult(
            {
                "version": "1",
                "revision": current["revision"],
                "review": review,
                "blocker_count": sum(1 for item in review["issues"] if item["severity"] == "blocker"),
            }
        )

    def _stage_editorial_review(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        current = self.revisions.current_review(job_id, "editorial")
        title = str(current["files"]["title.txt"]).strip()
        narration = str(current["files"]["narration.txt"]).strip()
        case_model = self._current_revision_files(job_id, "case-model")["case_model.json"]
        excerpts = self._model_source_excerpts(
            self._read_json(self.storage.job_root(job_id) / "source" / "external_boundary.json", "editorial.review")
        )
        model_review = self.model_gateway.run_json(
            "editorial.review",
            "v1",
            {
                "task": "editorial.review",
                "context": {
                    "project_name": manifest["project_name"],
                    "title": title,
                    "narration": narration,
                    "case_model": case_model,
                    "target_duration_seconds": manifest.get("target_duration_seconds") or {"min": 240, "max": 420},
                },
                "source_excerpts": excerpts,
                "constraints": {
                    "independent_review": True,
                    "checks": [
                        "title appeal and factual support",
                        "hook/title consistency",
                        "natural spoken Chinese",
                        "prohibited contrast patterns",
                        "acronym spacing",
                        "numeric readout risks",
                    ],
                },
            },
            job_id=job_id,
        )
        revision = self.revisions.create_editorial(
            job_id,
            title=title,
            narration=narration,
            change_summary="合并独立文稿审阅结果",
            author_type="model-review",
            actor="openai:gpt-5.5",
            review=model_review,
            input_hash=sha256_text(canonical_json(model_review)),
            enforce_concurrency=False,
        )
        final = self.revisions.current_review(job_id, "editorial")
        return StageResult(
            {
                "version": "1",
                "revision": revision["metadata"]["revision_id"],
                "reused": revision.get("reused", False),
                "review": final["files"]["review.json"],
                "route": {"provider": "openai", "model": "gpt-5.5"},
            }
        )

    def _stage_editorial_rewrite(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        active_request = self._active_model_revision_request(job_id, "editorial.rewrite", "editorial")
        if active_request is not None:
            current = self.revisions.current_review(job_id, "editorial")
            issues = active_request.get("issues") if isinstance(active_request.get("issues"), list) else []
            revision = self.revisions.create_editorial_model_revision(
                job_id,
                base_revision=str(active_request["base_revision"]),
                if_match=str(current["etag"]),
                feedback=str(active_request.get("feedback") or ""),
                issues=copy.deepcopy(issues),
                change_summary=str(active_request.get("change_summary") or "模型修订标题与旁白"),
                actor="azure-anthropic:salesnail-cs-46",
            )
            revision_id = str(revision["metadata"]["revision_id"])
            self._finish_model_revision_request(
                job_id,
                str(active_request["request_id"]),
                outcome="no_change" if revision.get("reused") else "created",
                result_revision=revision_id,
            )
            final = self.revisions.current_review(job_id, "editorial")
            return StageResult(
                {
                    "version": "1",
                    "request_id": active_request["request_id"],
                    "revision": revision_id,
                    "reused": revision.get("reused", False),
                    "remaining_blockers": final["blockers"],
                    "rewrite_route": {
                        "provider": "azure_anthropic",
                        "deployment": "salesnail-cs-46",
                        "transport": "anthropic_messages",
                    },
                    "review_route": {"provider": "openai", "model": "gpt-5.5"},
                }
            )
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, 3):
            current = self.revisions.current_review(job_id, "editorial")
            blockers = list(current["blockers"])
            if not blockers:
                break
            title = str(current["files"]["title.txt"]).strip()
            narration = str(current["files"]["narration.txt"]).strip()
            rewrite = self.model_gateway.run_json(
                "narration.rewrite",
                "v1",
                {
                    "task": "narration.rewrite",
                    "context": {
                        "project_name": manifest["project_name"],
                        "program": manifest.get("program", "销售不复杂"),
                        "title": title,
                        "narration": narration,
                        "target_duration_seconds": manifest.get("target_duration_seconds") or {"min": 240, "max": 420},
                    },
                    "issues": blockers,
                    "constraints": {
                        "fixed_opener": PROGRAM_OPENER,
                        "fixed_closer": PROGRAM_CLOSER,
                        "preserve_supported_facts": True,
                        "max_revision_attempts": 2,
                    },
                },
                job_id=job_id,
            )
            independent_review = self.model_gateway.run_json(
                "editorial.review",
                "v1",
                {
                    "task": "editorial.review",
                    "context": {
                        "project_name": manifest["project_name"],
                        "title": rewrite["title"],
                        "narration": rewrite["narration"],
                    },
                    "issues": [],
                    "constraints": {"independent_review": True, "post_rewrite_attempt": attempt},
                },
                job_id=job_id,
            )
            revision = self.revisions.create_editorial(
                job_id,
                title=rewrite["title"],
                narration=rewrite["narration"],
                change_summary=rewrite.get("change_summary", f"自动修订第 {attempt} 次"),
                author_type="model",
                actor="azure-anthropic:salesnail-cs-46",
                review=independent_review,
                input_hash=sha256_text(canonical_json({"attempt": attempt, "issues": blockers})),
                enforce_concurrency=False,
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "revision": revision["metadata"]["revision_id"],
                    "addressed_issue_ids": rewrite.get("addressed_issue_ids", []),
                }
            )
        final = self.revisions.current_review(job_id, "editorial")
        return StageResult(
            {
                "version": "1",
                "attempts": attempts,
                "max_attempts": 2,
                "revision": final["revision"],
                "remaining_blockers": final["blockers"],
                "rewrite_route": {
                    "provider": "azure_anthropic",
                    "deployment": "salesnail-cs-46",
                    "transport": "anthropic_messages",
                },
                "review_route": {"provider": "openai", "model": "gpt-5.5"},
            }
        )

    def _stage_editorial_approval(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        return self._approval_result(
            job_id,
            "editorial",
            manual_required=manifest.get("approval_mode") in {"editorial", "full"},
            display="等待标题与旁白审批",
        )

    def _stage_tts_generate(self, job_id: str) -> StageResult:
        project = self.storage.project_root(job_id)
        if self.settings.dry_run:
            timeline = self._write_dry_run_timeline(project)
            output = {
                "version": "1",
                "dry_run": True,
                "duration": timeline["duration"],
                "unit_count": len(timeline["units"]),
            }
        else:
            self._execute_argv(
                job_id,
                "tts.generate",
                (
                    str(self.settings.repo_root / "scripts" / "case-video"),
                    "tts",
                    str(project),
                    "--gender",
                    "female",
                    "--single-voice",
                    "--force",
                ),
            )
            timeline = self._read_json(project / "narration.timeline.json", "tts.generate")
            self.storage.contracts.validate("timeline", "v1", timeline, error_code="contract_invalid")
            output = {
                "version": "1",
                "dry_run": False,
                "duration": timeline.get("duration"),
                "unit_count": len(timeline.get("units", [])),
                "timeline_sha256": sha256_file(project / "narration.timeline.json"),
                "audio_sha256": sha256_file(project / "audio" / "narration_azure.wav"),
            }
        return StageResult(output)

    def _stage_visual_plan(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        editorial = self.revisions.current_review(job_id, "editorial")
        title = str(editorial["files"]["title.txt"]).strip()
        timeline = self._read_json(self.storage.project_root(job_id) / "narration.timeline.json", "visual.plan")
        units = timeline.get("units", [])
        plan = self.model_gateway.run_json(
            "remotion.plan",
            "v2",
            {
                "task": "remotion.plan",
                "context": {
                    "project_name": manifest["project_name"],
                    "program": manifest.get("program", "销售不复杂"),
                    "title": title,
                    "narration": str(editorial["files"]["narration.txt"]).strip(),
                    "unit_count": len(units),
                    "timeline_units": [
                        {"index": item.get("index"), "text": item.get("text")}
                        for item in units
                    ],
                },
                "constraints": {
                    "unit_anchor_base": 1,
                    "continuous_coverage": True,
                    "subtitle_label": manifest.get("program", "销售不复杂"),
                    "cover_title_must_equal_title": True,
                    "visual_family": "sales-management-silhouette",
                    "director_contract": "visual_plan/v2",
                    "adapter_must_not_invent_creative_choices": True,
                },
            },
            job_id=job_id,
        )
        plan_path = self.storage.job_root(job_id) / "stage-runs" / "visual.plan" / "plan.json"
        atomic_write_json(plan_path, plan)
        return StageResult(
            {
                "version": "2",
                "plan_path": plan_path.relative_to(self.storage.job_root(job_id)).as_posix(),
                "plan_sha256": sha256_file(plan_path),
                "scene_count": len(plan["scenes"]),
                "route": {
                    "provider": "azure_anthropic",
                    "deployment": "salesnail-cs-46",
                    "transport": "anthropic_messages",
                },
            }
        )

    def _stage_visual_build(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        plan = self._read_json(self.storage.job_root(job_id) / "stage-runs" / "visual.plan" / "plan.json", "visual.build")
        timeline = self._read_json(self.storage.project_root(job_id) / "narration.timeline.json", "visual.build")
        title = self._current_title(job_id)
        plan_version = str(plan.get("version", "1"))
        prompts = {"version": plan_version, "prompts": []}
        try:
            storyboard = build_rich_storyboard(
                plan,
                timeline,
                authored_title=title,
                project_name=manifest["project_name"],
                program=manifest.get("program", "销售不复杂"),
                image_prompts=prompts,
            )
        except ValueError as exc:
            raise AppError("readiness_blocked", str(exc), stage="visual.build") from exc
        revision = self.revisions.create_visual_plan(
            job_id,
            plan=plan,
            rich_storyboard=storyboard,
            image_prompts=prompts,
            change_summary="将 Claude 视觉计划转换为 Remotion 富分镜",
            author_type="pipeline-adapter",
            actor="pipeline",
            input_hash=sha256_text(canonical_json({"plan": plan, "timeline": timeline})),
            enforce_concurrency=False,
        )
        current = self.revisions.current_review(job_id, "visual-plan")
        return StageResult(
            {
                "version": plan_version,
                "revision": revision["metadata"]["revision_id"],
                "reused": revision.get("reused", False),
                "readiness": current["files"]["readiness.json"],
                "storyboard_sha256": sha256_file(self.storage.project_root(job_id) / "rich_storyboard.json"),
            }
        )

    def _stage_visual_repair(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        timeline = self._read_json(self.storage.project_root(job_id) / "narration.timeline.json", "visual.repair")
        active_request = self._active_model_revision_request(job_id, "visual.repair", "visual-plan")
        if active_request is not None:
            current = self.revisions.current_review(job_id, "visual-plan")
            issues = active_request.get("issues") if isinstance(active_request.get("issues"), list) else []
            scene_ids = active_request.get("scene_ids") if isinstance(active_request.get("scene_ids"), list) else []
            revision = self.revisions.create_visual_model_revision(
                job_id,
                base_revision=str(active_request["base_revision"]),
                if_match=str(current["etag"]),
                feedback=str(active_request.get("feedback") or ""),
                issues=copy.deepcopy(issues),
                scene_ids=[str(scene_id) for scene_id in scene_ids],
                change_summary=str(active_request.get("change_summary") or "模型修订视觉计划"),
                actor="azure-anthropic:salesnail-cs-46",
            )
            revision_id = str(revision["metadata"]["revision_id"])
            self._finish_model_revision_request(
                job_id,
                str(active_request["request_id"]),
                outcome="no_change" if revision.get("reused") else "created",
                result_revision=revision_id,
            )
            final = self.revisions.current_review(job_id, "visual-plan")
            return StageResult(
                {
                    "version": "2",
                    "request_id": active_request["request_id"],
                    "revision": revision_id,
                    "reused": revision.get("reused", False),
                    "remaining_blockers": final["blockers"],
                    "route": {
                        "provider": "azure_anthropic",
                        "deployment": "salesnail-cs-46",
                        "transport": "anthropic_messages",
                    },
                }
            )
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, 3):
            current = self.revisions.current_review(job_id, "visual-plan")
            blockers = list(current["blockers"])
            if not blockers:
                break
            plan = current["files"]["storyboard_plan.json"]
            repaired = self.model_gateway.run_json(
                "remotion.repair",
                "v2",
                {
                    "task": "remotion.repair",
                    "context": {
                        "project_name": manifest["project_name"],
                        "program": manifest.get("program", "销售不复杂"),
                        "title": self._current_title(job_id),
                        "unit_count": len(timeline.get("units", [])),
                        "visual_plan": plan,
                    },
                    "issues": blockers,
                    "constraints": {
                        "unit_anchor_base": 1,
                        "continuous_coverage": True,
                        "max_revision_attempts": 2,
                        "preserve_explicit_director_controls": True,
                    },
                },
                job_id=job_id,
            )
            try:
                storyboard = build_rich_storyboard(
                    repaired,
                    timeline,
                    authored_title=self._current_title(job_id),
                    project_name=manifest["project_name"],
                    program=manifest.get("program", "销售不复杂"),
                    image_prompts=current["files"].get("image_prompts.json"),
                )
            except ValueError as exc:
                raise AppError("readiness_blocked", str(exc), stage="visual.repair") from exc
            revision = self.revisions.create_visual_plan(
                job_id,
                plan=repaired,
                rich_storyboard=storyboard,
                image_prompts=current["files"].get("image_prompts.json"),
                change_summary=f"自动修复视觉计划第 {attempt} 次",
                author_type="model",
                actor="azure-anthropic:salesnail-cs-46",
                input_hash=sha256_text(canonical_json({"attempt": attempt, "issues": blockers})),
                enforce_concurrency=False,
            )
            attempts.append({"attempt": attempt, "revision": revision["metadata"]["revision_id"]})
        final = self.revisions.current_review(job_id, "visual-plan")
        return StageResult(
            {
                "version": "2",
                "attempts": attempts,
                "max_attempts": 2,
                "revision": final["revision"],
                "remaining_blockers": final["blockers"],
                "route": {
                    "provider": "azure_anthropic",
                    "deployment": "salesnail-cs-46",
                    "transport": "anthropic_messages",
                },
            }
        )

    def _stage_visual_contract_approval(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        checkpoint = manifest.get("approval_checkpoints", {}).get("visual_contract")
        if checkpoint:
            return StageResult(
                {
                    "version": "1",
                    "domain": "visual-plan",
                    "revision": checkpoint,
                    "approved": True,
                    "approval": "checkpoint",
                }
            )
        return self._approval_result(
            job_id,
            "visual-plan",
            manual_required=manifest.get("approval_mode") == "full",
            display="等待视觉合同审批",
        )

    def _stage_assets_generate(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        current = self.revisions.current_review(job_id, "visual-plan")
        plan = current["files"]["storyboard_plan.json"]
        if str(plan.get("version")) == "2":
            asset_context = [
                {
                    "asset_id": asset["id"],
                    "scene_id": asset["sceneId"],
                    "role": asset["role"],
                    "prompt_intent": asset["promptIntent"],
                    "continuity": asset.get("continuity", ""),
                }
                for asset in plan.get("assets", [])
            ]
        else:
            asset_context = [
                {
                    "asset_id": scene["scene_id"],
                    "scene_id": scene["scene_id"],
                    "role": "context",
                    "prompt_intent": scene["visual_intent"],
                    "continuity": "",
                }
                for scene in plan.get("scenes", [])
                if not scene.get("reuse") and not scene.get("allowBackgroundReuse")
            ]
        prompts = self.model_gateway.run_json(
            "image_prompt.refine",
            "v2",
            {
                "task": "image_prompt.refine",
                "context": {
                    "project_name": manifest["project_name"],
                    "asset_ids": [asset["asset_id"] for asset in asset_context],
                    "assets": asset_context,
                    "approved_visual_revision": current["revision"],
                },
                "constraints": {
                    "style_family": "sales-management-silhouette",
                    "forbid": ["logos", "readable text", "numerals", "letters", "watermarks", "UI screenshots"],
                    "fresh_project_local_assets": True,
                },
            },
            job_id=job_id,
        )
        project = self.storage.project_root(job_id)
        timeline = self._read_json(project / "narration.timeline.json", "assets.generate")
        try:
            storyboard = build_rich_storyboard(
                plan,
                timeline,
                authored_title=self._current_title(job_id),
                project_name=manifest["project_name"],
                program=manifest.get("program", "销售不复杂"),
                image_prompts=prompts,
            )
        except ValueError as exc:
            raise AppError("readiness_blocked", str(exc), stage="assets.generate") from exc
        revision = self.revisions.create_visual_plan(
            job_id,
            plan=plan,
            rich_storyboard=storyboard,
            image_prompts=prompts,
            change_summary="绑定图像提示词与项目视觉资产",
            author_type="model",
            actor="openai:gpt-5.5",
            input_hash=sha256_text(canonical_json({"plan": plan, "prompts": prompts})),
            enforce_concurrency=False,
            invalidate_stage_runs=False,
        )
        visual_revision = revision["metadata"]["revision_id"]
        if self.settings.dry_run:
            self._write_dry_run_images(project, prompts)
        else:
            self._execute_argv(
                job_id,
                "assets.generate",
                (str(self.settings.repo_root / "scripts" / "case-video"), "images", str(project)),
            )
        image_records = []
        for prompt in prompts["prompts"]:
            relative = prompt_image_path(prompt)
            if relative is None:
                raise AppError(
                    "contract_invalid",
                    "image prompt does not resolve to a safe project-local path",
                    stage="assets.generate",
                )
            path = project / relative
            prompt_id = str(prompt.get("asset_id") or prompt.get("scene_id"))
            image_records.append(
                {
                    "asset_id": prompt_id,
                    "path": relative,
                    "exists": path.is_file(),
                    "sha256": sha256_file(path) if path.is_file() else None,
                }
            )
        missing = [item["asset_id"] for item in image_records if not item["exists"]]
        if missing:
            raise AppError(
                "artifact_corrupt",
                f"generated images are missing for assets: {', '.join(missing)}",
                stage="assets.generate",
            )
        return StageResult(
            {
                "version": "2",
                "source_approved_visual_revision": current["revision"],
                "visual_revision": visual_revision,
                "prompt_count": len(prompts["prompts"]),
                "images": image_records,
                "route": {"provider": "openai", "model": "gpt-5.5"},
                "dry_run": self.settings.dry_run,
            }
        )

    def _stage_visual_preview(self, job_id: str) -> StageResult:
        manifest = self._render_intent_preview(job_id, stage="visual.preview")
        return StageResult(
            {
                "version": "1",
                "composition": manifest["composition"],
                "frame_count": manifest["frame_count"],
                "frames": [
                    {
                        "frame_id": item["frame_id"],
                        "scene_id": item["scene_id"],
                        "beat_id": item.get("beat_id"),
                        "file": item["file"],
                        "sha256": item["sha256"],
                    }
                    for item in manifest["frames"]
                ],
                "dry_run": self.settings.dry_run,
            }
        )

    def _stage_visual_intent_review(self, job_id: str) -> StageResult:
        project = self.storage.project_root(job_id)
        qa_root = project / "qa"
        qa_root.mkdir(parents=True, exist_ok=True)
        attempts: list[dict[str, Any]] = []

        frame_manifest = self._load_intent_frame_manifest(job_id, stage="visual.intent-review")
        review = self._review_intent_frames(job_id, frame_manifest)
        atomic_write_json(qa_root / "intent-frame-review.attempt-1.json", review)
        attempts.append({"attempt": 1, "verdict": review["verdict"], "issue_count": len(review["issues"])})

        if review["verdict"] == "blocked":
            atomic_write_json(qa_root / "intent-frame-review.json", review)
            raise AppError(
                "semantic_review_blocked",
                "代表帧审片判定现有素材与导演合同无法通过编排修复",
                stage="visual.intent-review",
                public_details={"review": "qa/intent-frame-review.json"},
            )

        repaired_revision: str | None = None
        if review["verdict"] == "revise":
            repaired_revision = self._repair_from_intent_review(job_id, review)
            frame_manifest = self._render_intent_preview(job_id, stage="visual.intent-review")
            review = self._review_intent_frames(job_id, frame_manifest)
            atomic_write_json(qa_root / "intent-frame-review.attempt-2.json", review)
            attempts.append({"attempt": 2, "verdict": review["verdict"], "issue_count": len(review["issues"])})

        atomic_write_json(qa_root / "intent-frame-review.json", review)
        if review["verdict"] != "pass":
            raise AppError(
                "semantic_review_blocked",
                "代表帧在一次受限导演修订后仍未通过意图审片",
                stage="visual.intent-review",
                public_details={"review": "qa/intent-frame-review.json", "attempts": attempts},
            )
        return StageResult(
            {
                "version": "1",
                "verdict": "pass",
                "attempts": attempts,
                "repaired_revision": repaired_revision,
                "review": "qa/intent-frame-review.json",
                "frame_count": frame_manifest["frame_count"],
                "route": {"provider": "openai", "model": "gpt-5.5"},
            }
        )

    def _stage_visual_approval(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        return self._approval_result(
            job_id,
            "visual-plan",
            manual_required=manifest.get("approval_mode") == "full",
            display="等待成片视觉审批",
        )

    def _stage_render_prepare(self, job_id: str) -> StageResult:
        project = self.storage.project_root(job_id)
        if self.settings.dry_run:
            required = [
                "title.txt",
                "narration.txt",
                "narration.timeline.json",
                "storyboard_plan.json",
                "rich_storyboard.json",
                "image_prompts.json",
                "audio/narration_azure.wav",
            ]
            checks = {name: (project / name).is_file() for name in required}
            if not all(checks.values()):
                missing = [name for name, exists in checks.items() if not exists]
                raise AppError("readiness_blocked", f"render inputs missing: {', '.join(missing)}", stage="render.prepare")
            report = {"version": "1", "status": "ready", "dry_run": True, "checks": checks}
            atomic_write_json(project / "qa" / "render-readiness.json", report)
            return StageResult(report)

        commands = (
            (str(self.settings.repo_root / "scripts" / "case-video"), "check", str(project)),
            (str(self.settings.repo_root / "scripts" / "case-video"), "evaluate", str(project)),
            (str(self.settings.repo_root / "scripts" / "case-video"), "ready", str(project), "--stage", "render"),
            (str(self.settings.repo_root / "scripts" / "case-video"), "typecheck", str(project)),
        )
        for command in commands:
            self._execute_argv(job_id, "render.prepare", command)
        report = {"version": "1", "status": "ready", "dry_run": False, "commands": [list(item) for item in commands]}
        atomic_write_json(project / "qa" / "render-readiness.json", report)
        return StageResult(report)

    def _stage_render_execute(self, job_id: str) -> StageResult:
        project = self.storage.project_root(job_id)
        if self.settings.dry_run:
            report = {
                "version": "1",
                "status": "simulated",
                "dry_run": True,
                "would_run": [str(self.settings.repo_root / "scripts" / "case-video"), "render", str(project)],
            }
            atomic_write_json(project / "video" / "render-dry-run.json", report)
            return StageResult(report)
        if self.render_runner is not None:
            try:
                self.render_runner.run(
                    job_id,
                    project,
                    cancel_requested=lambda: bool(self.storage.read_manifest(job_id).get("cancel_requested")),
                )
            except RenderIsolationError as exc:
                raise AppError(
                    "render_isolation_failed",
                    str(exc),
                    retryable=True,
                    stage="render.execute",
                ) from exc
        else:
            self._execute_argv(
                job_id,
                "render.execute",
                (str(self.settings.repo_root / "scripts" / "case-video"), "render", str(project)),
            )
        video = project / "video" / "case_video.mp4"
        if not video.is_file() or video.stat().st_size == 0:
            raise AppError("artifact_corrupt", "Remotion render did not produce case_video.mp4", stage="render.execute")
        return StageResult(
            {
                "version": "1",
                "video": "video/case_video.mp4",
                "size": video.stat().st_size,
                "sha256": sha256_file(video),
            }
        )

    def _stage_qa_execute(self, job_id: str) -> StageResult:
        project = self.storage.project_root(job_id)
        qa_path = project / "qa" / "server-delivery-qa.json"
        if self.settings.dry_run:
            timeline = self._read_json(project / "narration.timeline.json", "qa.execute")
            report = {
                "version": "1",
                "status": "pass",
                "dry_run": True,
                "simulated": True,
                "checks": {
                    "timeline_contract": True,
                    "storyboard_present": (project / "rich_storyboard.json").is_file(),
                    "generated_images_present": bool(list((project / "images" / "generated").glob("*.png"))),
                },
                "narration_duration": timeline.get("duration"),
                "note": "dry-run 仅用于流水线合同验收，不替代真实 ffprobe/视觉 QA。",
            }
            atomic_write_json(qa_path, report)
            return StageResult(report)

        self._execute_argv(
            job_id,
            "qa.execute",
            (str(self.settings.repo_root / "scripts" / "case-video"), "qa", str(project)),
        )
        self._execute_argv(
            job_id,
            "qa.execute",
            ("python3", str(self.settings.repo_root / "scripts" / "extract_video_qa.py"), str(project), "--skip-beats"),
        )
        report = self._probe_render(project)
        atomic_write_json(qa_path, report)
        if report["status"] != "pass":
            raise AppError(
                "readiness_blocked",
                "video QA failed: " + "; ".join(report["failures"]),
                stage="qa.execute",
            )
        return StageResult(report)

    def _stage_delivery_finalize(self, job_id: str) -> StageResult:
        manifest = self.storage.read_manifest(job_id)
        qa_path = self.storage.project_root(job_id) / "qa" / "server-delivery-qa.json"
        qa = self._read_json(qa_path, "delivery.finalize")
        preliminary = self.storage.list_artifacts(job_id)
        summary = self.model_gateway.run_json(
            "delivery.summarize",
            "v1",
            {
                "task": "delivery.summarize",
                "context": {
                    "project_name": manifest["project_name"],
                    "qa": qa,
                    "artifact_count": len(preliminary),
                    "current_revisions": manifest.get("current_revisions", {}),
                    "approved_revisions": manifest.get("approved_revisions", {}),
                    "model_routes": manifest.get("model_routes", {}),
                },
                "constraints": {"summarize_only_verified_results": True},
            },
            job_id=job_id,
        )
        if qa.get("status") != "pass":
            summary = {
                "version": "1",
                "status": "blocked",
                "summary": "交付 QA 尚未通过。",
                "qa_highlights": [],
                "remaining_risks": list(qa.get("failures", [])),
            }
        self.storage.contracts.validate("delivery_summary", "v1", summary)
        summary_path = self.storage.job_root(job_id) / "delivery_summary.json"
        atomic_write_json(summary_path, summary)

        indexed: list[dict[str, Any]] = []
        for artifact in self.storage.list_artifacts(job_id):
            if artifact["name"] in {"artifact_index.json", "job_manifest.json"} or artifact["name"].startswith("stage-runs/delivery.finalize/"):
                continue
            path = self.storage.artifact_path(job_id, artifact["name"])
            indexed.append(
                {
                    "name": artifact["name"],
                    "size": artifact["size"],
                    "sha256": sha256_file(path),
                    "kind": artifact["kind"],
                    "current": artifact["current"],
                    "revision": self._artifact_revision(manifest, artifact["name"]),
                }
            )
        artifact_index = {"version": "1", "artifacts": indexed}
        self.storage.contracts.validate("artifact_index", "v1", artifact_index)
        index_path = self.storage.job_root(job_id) / "artifact_index.json"
        atomic_write_json(index_path, artifact_index)
        index_sha = sha256_file(index_path)
        manifest = self.storage.read_manifest(job_id)
        manifest["artifact_index_sha256"] = index_sha
        self.storage.write_manifest(job_id, manifest)
        return StageResult(
            {
                "version": "1",
                "summary": summary,
                "artifact_count": len(indexed),
                "artifact_index_sha256": index_sha,
                "route": {"provider": "openai", "model": "gpt-5.5"},
            }
        )

    def _render_intent_preview(self, job_id: str, *, stage: str) -> dict[str, Any]:
        project = self.storage.project_root(job_id)
        output_root = project / "qa" / "intent-frames"
        if self.settings.dry_run:
            storyboard = self._read_json(project / "rich_storyboard.json", stage)
            timeline = self._read_json(project / "narration.timeline.json", stage)
            try:
                frames = select_intent_frames(storyboard, timeline, max_frames=24)
            except (KeyError, TypeError, ValueError) as exc:
                raise AppError("contract_invalid", str(exc), stage=stage) from exc
            output_root.mkdir(parents=True, exist_ok=True)
            for old_frame in output_root.glob("frame-*.png"):
                old_frame.unlink()
            pixel = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            for record in frames:
                (output_root / record["file"]).write_bytes(pixel)
            atomic_write_json(
                output_root / "manifest.json",
                {
                    "version": "1",
                    "composition": "CaseVideoIntentReview",
                    "fps": int(storyboard.get("fps", 30)),
                    "frame_count": len(frames),
                    "frames": frames,
                },
            )
        else:
            self._execute_argv(
                job_id,
                stage,
                (
                    str(self.settings.repo_root / "scripts" / "case-video"),
                    "intent-frames",
                    str(project),
                    "--max-frames",
                    "24",
                ),
            )
        return self._load_intent_frame_manifest(job_id, stage=stage)

    def _load_intent_frame_manifest(self, job_id: str, *, stage: str) -> dict[str, Any]:
        project = self.storage.project_root(job_id)
        root = project / "qa" / "intent-frames"
        manifest = self._read_json(root / "manifest.json", stage)
        frames = manifest.get("frames")
        if manifest.get("version") != "1" or manifest.get("composition") != "CaseVideoIntentReview":
            raise AppError("contract_invalid", "intent frame manifest has an unsupported contract", stage=stage)
        if not isinstance(frames, list) or not frames or manifest.get("frame_count") != len(frames):
            raise AppError("artifact_corrupt", "intent frame manifest has invalid frame records", stage=stage)

        storyboard = self._read_json(project / "rich_storyboard.json", stage)
        expected_scenes = {str(scene.get("id")) for scene in storyboard.get("scenes", [])}
        seen_frames: set[str] = set()
        seen_files: set[str] = set()
        seen_scenes: set[str] = set()
        checked_frames: list[dict[str, Any]] = []
        for item in frames:
            if not isinstance(item, dict):
                raise AppError("contract_invalid", "intent frame record must be an object", stage=stage)
            frame_id = str(item.get("frame_id", "")).strip()
            scene_id = str(item.get("scene_id", "")).strip()
            filename = str(item.get("file", "")).strip()
            if not frame_id or not scene_id or not re.fullmatch(r"frame-\d{3}\.png", filename):
                raise AppError("contract_invalid", "intent frame record has invalid identifiers", stage=stage)
            if frame_id in seen_frames or filename in seen_files:
                raise AppError("contract_invalid", "intent frame identifiers must be unique", stage=stage)
            path = root / filename
            if not path.is_file() or path.stat().st_size == 0:
                raise AppError("artifact_corrupt", f"intent frame is missing: {filename}", stage=stage)
            seen_frames.add(frame_id)
            seen_files.add(filename)
            seen_scenes.add(scene_id)
            checked_frames.append({**item, "sha256": sha256_file(path)})
        if seen_scenes != expected_scenes:
            missing = sorted(expected_scenes - seen_scenes)
            extra = sorted(seen_scenes - expected_scenes)
            raise AppError(
                "contract_invalid",
                f"intent frames must cover every scene; missing={missing}, extra={extra}",
                stage=stage,
            )
        return {**manifest, "frames": checked_frames}

    def _review_intent_frames(self, job_id: str, frame_manifest: dict[str, Any]) -> dict[str, Any]:
        project = self.storage.project_root(job_id)
        current = self.revisions.current_review(job_id, "visual-plan")
        plan = current["files"]["storyboard_plan.json"]
        scene_groups: dict[str, list[dict[str, Any]]] = {}
        for frame in frame_manifest["frames"]:
            scene_groups.setdefault(str(frame["scene_id"]), []).append(frame)

        batches: list[list[dict[str, Any]]] = []
        pending: list[dict[str, Any]] = []
        for group in scene_groups.values():
            if len(group) > 32:
                raise AppError(
                    "contract_invalid",
                    "a single scene produced more than 32 intent frames",
                    stage="visual.intent-review",
                )
            if pending and len(pending) + len(group) > 24:
                batches.append(pending)
                pending = []
            pending.extend(group)
        if pending:
            batches.append(pending)

        reviews: list[dict[str, Any]] = []
        for batch_index, batch in enumerate(batches, start=1):
            media = []
            for frame in batch:
                path = project / "qa" / "intent-frames" / frame["file"]
                mime_type, encoded = self._encode_intent_frame(path)
                media.append(
                    {
                        "media_id": frame["frame_id"],
                        "mime_type": mime_type,
                        "data_base64": encoded,
                        "description": intent_frame_description(frame),
                    }
                )
            review = self.model_gateway.run_json(
                "remotion.frame-review",
                "v1",
                {
                    "task": "remotion.frame-review",
                    "context": {
                        "project_name": self.storage.read_manifest(job_id)["project_name"],
                        "title": self._current_title(job_id),
                        "visual_revision": current["revision"],
                        "direction": plan.get("direction", {}),
                        "frames": [
                            {key: value for key, value in frame.items() if key != "sha256"}
                            for frame in batch
                        ],
                    },
                    "media": media,
                    "constraints": {
                        "judge_pixels_against_declared_intent": True,
                        "do_not_impose_personal_style": True,
                        "repair_must_preserve_narration_timeline_and_assets": True,
                    },
                },
                job_id=job_id,
            )
            self._validate_frame_review_evidence(review, batch)
            for issue in review["issues"]:
                issue["issue_id"] = f"batch-{batch_index:02d}-{issue['issue_id']}"
            reviews.append(review)

        verdict = "pass"
        if any(review["verdict"] == "blocked" for review in reviews):
            verdict = "blocked"
        elif any(review["verdict"] == "revise" for review in reviews):
            verdict = "revise"
        summary = "\n".join(review["summary"] for review in reviews)
        combined = {
            "version": "1",
            "verdict": verdict,
            "summary": summary[:3000],
            "scene_reviews": [item for review in reviews for item in review["scene_reviews"]],
            "issues": [item for review in reviews for item in review["issues"]],
        }
        self.storage.contracts.validate("frame_review", "v1", combined, error_code="model_output_invalid")
        return combined

    @staticmethod
    def _validate_frame_review_evidence(review: dict[str, Any], frames: list[dict[str, Any]]) -> None:
        expected_frames = {str(item["frame_id"]) for item in frames}
        expected_scenes = {str(item["scene_id"]) for item in frames}
        expected_by_scene: dict[str, set[str]] = {}
        for frame in frames:
            expected_by_scene.setdefault(str(frame["scene_id"]), set()).add(str(frame["frame_id"]))
        scene_reviews = review.get("scene_reviews", [])
        reviewed_scene_ids = [str(item["scene_id"]) for item in scene_reviews]
        reviewed_frame_ids = [
            str(frame_id)
            for item in scene_reviews
            for frame_id in item.get("frame_ids", [])
        ]
        if (
            set(reviewed_scene_ids) != expected_scenes
            or len(reviewed_scene_ids) != len(expected_scenes)
            or set(reviewed_frame_ids) != expected_frames
            or len(reviewed_frame_ids) != len(expected_frames)
        ):
            raise AppError(
                "model_output_invalid",
                "frame review must cite every provided scene and frame exactly",
                stage="visual.intent-review",
            )
        for item in scene_reviews:
            scene_id = str(item["scene_id"])
            if set(str(frame_id) for frame_id in item.get("frame_ids", [])) != expected_by_scene[scene_id]:
                raise AppError(
                    "model_output_invalid",
                    "frame review must cite each frame under its actual scene",
                    stage="visual.intent-review",
                )
        for issue in review.get("issues", []):
            if issue.get("scene_id") not in expected_scenes:
                raise AppError("model_output_invalid", "frame review cites an unknown scene", stage="visual.intent-review")
            if issue.get("frame_id") and issue["frame_id"] not in expected_frames:
                raise AppError("model_output_invalid", "frame review cites an unknown frame", stage="visual.intent-review")
            if issue.get("frame_id") and issue["frame_id"] not in expected_by_scene[str(issue["scene_id"])]:
                raise AppError(
                    "model_output_invalid",
                    "frame review issue cites a frame from another scene",
                    stage="visual.intent-review",
                )

    @staticmethod
    def _encode_intent_frame(path: Path) -> tuple[str, str]:
        try:
            with Image.open(path) as image:
                image = image.convert("RGB")
                image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True)
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(
                "artifact_corrupt",
                f"intent frame cannot be decoded: {path.name}",
                stage="visual.intent-review",
            ) from exc
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        if len(encoded) > 8_000_000:
            raise AppError(
                "artifact_corrupt",
                f"intent frame exceeds the review media contract: {path.name}",
                stage="visual.intent-review",
            )
        return "image/jpeg", encoded

    def _repair_from_intent_review(self, job_id: str, review: dict[str, Any]) -> str:
        manifest = self.storage.read_manifest(job_id)
        current = self.revisions.current_review(job_id, "visual-plan")
        plan = current["files"]["storyboard_plan.json"]
        prompts = current["files"]["image_prompts.json"]
        timeline = self._read_json(
            self.storage.project_root(job_id) / "narration.timeline.json",
            "visual.intent-review",
        )
        repaired = self.model_gateway.run_json(
            "remotion.repair",
            "v2",
            {
                "task": "remotion.repair",
                "context": {
                    "project_name": manifest["project_name"],
                    "program": manifest.get("program", "销售不复杂"),
                    "title": self._current_title(job_id),
                    "unit_count": len(timeline.get("units", [])),
                    "visual_plan": plan,
                    "frame_review_summary": review["summary"],
                },
                "issues": review["issues"],
                "constraints": {
                    "repair_scope": "composition-only",
                    "max_revision_attempts": 1,
                    "preserve_title_facts_timeline_scene_ranges_assets_and_directorial_intent": True,
                    "allowed_changes": [
                        "composition and asset fit/crop",
                        "boxes",
                        "slots",
                        "layer visibility and timing",
                        "beat boundaries inside the same scene",
                        "camera paths",
                        "treatment colors",
                        "transitions",
                        "local chrome",
                    ],
                },
            },
            job_id=job_id,
        )
        self._assert_intent_repair_scope(plan, repaired)
        try:
            storyboard = build_rich_storyboard(
                repaired,
                timeline,
                authored_title=self._current_title(job_id),
                project_name=manifest["project_name"],
                program=manifest.get("program", "销售不复杂"),
                image_prompts=prompts,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError("readiness_blocked", str(exc), stage="visual.intent-review") from exc
        revision = self.revisions.create_visual_plan(
            job_id,
            plan=repaired,
            rich_storyboard=storyboard,
            image_prompts=prompts,
            change_summary="根据代表帧审片执行一次受限导演修订",
            author_type="model",
            actor="azure-anthropic:salesnail-cs-46",
            input_hash=sha256_text(canonical_json({"revision": current["revision"], "issues": review["issues"]})),
            enforce_concurrency=False,
            invalidate_stage_runs=False,
        )
        return revision["metadata"]["revision_id"]

    @classmethod
    def _assert_intent_repair_scope(cls, before: dict[str, Any], after: dict[str, Any]) -> None:
        if cls._intent_repair_invariants(before) != cls._intent_repair_invariants(after):
            raise AppError(
                "semantic_review_blocked",
                "intent-frame repair changed protected content, scene structure, assets, or directorial intent",
                stage="visual.intent-review",
            )

    @staticmethod
    def _intent_repair_invariants(plan: dict[str, Any]) -> dict[str, Any]:
        layer_content_keys = (
            "id",
            "kind",
            "asset",
            "label",
            "text",
            "value",
            "bars",
            "nodes",
            "links",
            "speaker",
            "shape",
        )
        scenes = []
        for scene in plan.get("scenes", []):
            headline = scene.get("headline") or {}
            scenes.append(
                {
                    "id": scene.get("id"),
                    "units": scene.get("units"),
                    "chapter": scene.get("chapter"),
                    "kicker": scene.get("kicker"),
                    "layout": scene.get("layout"),
                    "visualMode": scene.get("visualMode"),
                    "dramaticFunction": scene.get("dramaticFunction"),
                    "directorialIntent": scene.get("directorialIntent"),
                    "headline": {"text": headline.get("text"), "accent": headline.get("accent")},
                    "keyword_text": [item.get("text") for item in scene.get("keywords", [])],
                    "background_assets": [item.get("asset") for item in scene.get("backgrounds", [])],
                    "beats": [
                        {
                            "id": beat.get("id"),
                            "visualIntent": beat.get("visualIntent"),
                            "purpose": beat.get("purpose"),
                            "directorialIntent": beat.get("directorialIntent"),
                            "baseAsset": beat.get("baseAsset"),
                            "layers": [
                                {key: layer.get(key) for key in layer_content_keys if key in layer}
                                for layer in beat.get("layers", [])
                            ],
                        }
                        for beat in scene.get("visualBeats", [])
                    ],
                }
            )
        return {
            "version": plan.get("version"),
            "width": plan.get("width"),
            "height": plan.get("height"),
            "fps": plan.get("fps"),
            "brand": plan.get("brand"),
            "subtitleLabel": plan.get("subtitleLabel"),
            "cover": plan.get("cover"),
            "direction": plan.get("direction"),
            "assets": plan.get("assets"),
            "scenes": scenes,
        }

    def _approval_result(
        self,
        job_id: str,
        domain: str,
        *,
        manual_required: bool,
        display: str,
    ) -> StageResult:
        review = self.revisions.current_review(job_id, domain)
        if review["is_approved"]:
            return StageResult(
                {
                    "version": "1",
                    "domain": domain,
                    "revision": review["revision"],
                    "approved": True,
                    "approval": "existing",
                }
            )
        if review["blockers"]:
            return StageResult(
                {
                    "version": "1",
                    "domain": domain,
                    "revision": review["revision"],
                    "approved": False,
                    "blockers": review["blockers"],
                },
                paused=True,
                display_status=f"{display}：存在 blocker",
                next_action="处理当前版本的 blocker 后重新提交",
                can_approve=False,
            )
        if review["is_rejected"]:
            return StageResult(
                {
                    "version": "1",
                    "domain": domain,
                    "revision": review["revision"],
                    "approved": False,
                    "rejected": True,
                },
                paused=True,
                display_status=f"{display}：当前版本已驳回",
                next_action="修改内容或提交模型修订",
                can_approve=False,
            )
        if manual_required:
            return StageResult(
                {
                    "version": "1",
                    "domain": domain,
                    "revision": review["revision"],
                    "etag": review["etag"],
                    "approved": False,
                    "blockers": [],
                },
                paused=True,
                display_status=display,
                next_action=f"审核并批准 {review['revision']}",
                can_approve=review["can_approve"],
            )
        self.revisions.approve(
            job_id,
            domain,
            revision_id=review["revision"],
            base_revision=review["revision"],
            if_match=review["etag"],
            has_unsaved_draft=False,
            actor="pipeline:auto",
            reason="approval_mode 自动批准",
        )
        return StageResult(
            {
                "version": "1",
                "domain": domain,
                "revision": review["revision"],
                "approved": True,
                "approval": "automatic",
            }
        )

    # ------------------------------------------------------------------
    # Shared helpers

    def _current_revision_files(self, job_id: str, domain: str) -> dict[str, Any]:
        manifest_key = domain.replace("-", "_")
        revision_id = self.storage.read_manifest(job_id).get("current_revisions", {}).get(manifest_key)
        if not revision_id:
            raise AppError("approval_required", f"no current {domain} revision", stage=self.storage.read_manifest(job_id).get("stage"))
        return self.revisions.get_revision(job_id, domain, revision_id)["files"]

    def _current_title(self, job_id: str) -> str:
        return str(self._current_revision_files(job_id, "editorial")["title.txt"]).strip()

    @staticmethod
    def _model_source_excerpts(boundary: dict[str, Any]) -> list[dict[str, Any]]:
        excerpts: list[dict[str, Any]] = []
        for item in boundary.get("sources", []):
            text = str(item.get("excerpt", "")).strip()
            if not text:
                continue
            excerpts.append(
                {
                    "source_id": str(item["source_id"]),
                    "locator": str(item.get("policy") or "structured_excerpt"),
                    "text": text,
                }
            )
        if not excerpts:
            raise AppError("source_invalid", "external source boundary contains no usable excerpts")
        return excerpts

    @staticmethod
    def _read_json(path: Path, stage: str) -> dict[str, Any]:
        if not path.is_file():
            raise AppError("artifact_corrupt", f"required JSON artifact is missing: {path.name}", stage=stage)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError("artifact_corrupt", f"invalid JSON artifact: {path.name}", stage=stage) from exc
        if not isinstance(payload, dict):
            raise AppError("contract_invalid", f"JSON artifact must be an object: {path.name}", stage=stage)
        return payload

    def _write_dry_run_timeline(self, project: Path) -> dict[str, Any]:
        narration = (project / "narration.txt").read_text(encoding="utf-8").strip()
        segments = [item.strip() for item in re.findall(r"[^。！？；\n]+[。！？；]?", narration) if item.strip()]
        if not segments:
            raise AppError("contract_invalid", "narration cannot produce timeline units", stage="tts.generate")
        units: list[dict[str, Any]] = []
        cursor = 0.0
        for index, text in enumerate(segments, start=1):
            duration = max(0.8, len(re.sub(r"\s+", "", text)) / 4.0)
            end = round(cursor + duration, 3)
            units.append({"index": index, "text": text, "start": round(cursor, 3), "end": end})
            cursor = end
        timeline = {"duration": round(cursor, 3), "units": units}
        self.storage.contracts.validate("timeline", "v1", timeline)
        atomic_write_json(project / "narration.timeline.json", timeline)
        atomic_write_text(project / "narration.tts.txt", narration + "\n")
        atomic_write_text(project / "narration.tts.plan.txt", "dry-run single-voice Azure Speech plan\n")
        audio = project / "audio" / "narration_azure.wav"
        audio.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16_000)
            handle.writeframes(b"\x00\x00" * 1_600)
        return timeline

    @staticmethod
    def _write_dry_run_images(project: Path, prompts: dict[str, Any]) -> None:
        # Valid 1x1 PNG. It is deliberately marked dry-run and never accepted as
        # a real delivery background; its purpose is filesystem contract testing.
        pixel = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        for prompt in prompts.get("prompts", []):
            relative = prompt_image_path(prompt)
            if relative is None:
                raise AppError(
                    "contract_invalid",
                    "dry-run image prompt does not resolve to a safe project-local path",
                    stage="assets.generate",
                )
            destination = project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(pixel)

    def _probe_render(self, project: Path) -> dict[str, Any]:
        video = project / "video" / "case_video.mp4"
        if not video.is_file():
            return {"version": "1", "status": "blocked", "dry_run": False, "failures": ["case_video.mp4 missing"]}
        try:
            completed = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(video),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=min(120, self.settings.command_timeout_seconds),
            )
            probe = json.loads(completed.stdout)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            raise AppError("artifact_corrupt", "ffprobe could not inspect rendered video", stage="qa.execute") from exc
        streams = probe.get("streams", [])
        video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
        failures: list[str] = []
        if video_stream is None:
            failures.append("video stream missing")
        if audio_stream is None:
            failures.append("audio stream missing")
        if video_stream and (video_stream.get("width"), video_stream.get("height")) != (1920, 1080):
            failures.append("video resolution is not 1920x1080")
        if video_stream:
            rate = str(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1")
            try:
                numerator, denominator = rate.split("/", 1)
                fps = float(numerator) / float(denominator)
            except (ValueError, ZeroDivisionError):
                fps = 0.0
            if abs(fps - 30.0) > 0.1:
                failures.append(f"video frame rate is {fps:.3f}, expected 30")
        timeline = self._read_json(project / "narration.timeline.json", "qa.execute")
        narration_duration = float(timeline.get("duration") or timeline.get("units", [{}])[-1].get("end") or 0)
        try:
            video_duration = float(probe.get("format", {}).get("duration") or 0)
        except (TypeError, ValueError):
            video_duration = 0.0
        if video_duration <= 0:
            failures.append("video duration is unavailable")
        elif abs(video_duration - narration_duration) > max(2.0, narration_duration * 0.02):
            failures.append(
                f"video/audio timeline duration mismatch: video={video_duration:.3f}s timeline={narration_duration:.3f}s"
            )
        return {
            "version": "1",
            "status": "blocked" if failures else "pass",
            "dry_run": False,
            "failures": failures,
            "video": {
                "path": "video/case_video.mp4",
                "sha256": sha256_file(video),
                "size": video.stat().st_size,
                "duration": video_duration,
                "width": video_stream.get("width") if video_stream else None,
                "height": video_stream.get("height") if video_stream else None,
            },
            "audio_stream_present": audio_stream is not None,
            "narration_duration": narration_duration,
            "contact_sheet_present": any((project / "qa").glob("*contact*")),
        }

    @staticmethod
    def _artifact_revision(manifest: dict[str, Any], name: str) -> str | None:
        if name.endswith(("title.txt", "narration.txt", "review.json")):
            return manifest.get("current_revisions", {}).get("editorial")
        if name.endswith(("storyboard_plan.json", "rich_storyboard.json", "image_prompts.json", "readiness.json")):
            return manifest.get("current_revisions", {}).get("visual_plan")
        if name.endswith("case_model.json"):
            return manifest.get("current_revisions", {}).get("case_model")
        return None

    def _complete_job(self, job_id: str) -> dict[str, Any]:
        artifacts = self.storage.list_artifacts(job_id)
        final_manifest = self.storage.read_manifest(job_id)
        final_manifest.update(
            {
                "status": JobStatus.succeeded.value,
                "display_status": "已完成",
                "stage": "succeeded",
                "overall_progress": 1.0,
                "stage_progress": {"stage": "succeeded", "status": "succeeded", "message": "任务完成"},
                "needs_action": False,
                "next_action": "下载成片或产物",
                "can_approve": False,
                "can_cancel": False,
                "can_retry": False,
                "artifacts": artifacts,
                "last_heartbeat_at": utc_now_iso(),
            }
        )
        self.storage.write_manifest(job_id, final_manifest)
        self.storage.append_event(
            job_id,
            "job.succeeded",
            "succeeded",
            "任务已完成",
            {"artifact_count": len(artifacts)},
        )
        return final_manifest

    # ------------------------------------------------------------------
    # Legacy Phase A executor

    def _run_stage(
        self,
        job_id: str,
        stage: PipelineStage,
        index: int,
        total: int,
        force: bool,
    ) -> None:
        input_hash = self.storage.project_input_hash(job_id, stage.input_files)
        manifest = self.storage.read_manifest(job_id)
        previous = manifest.get("stage_runs", {}).get(stage.name)
        if previous and previous.get("status") == "succeeded" and previous.get("input_hash") == input_hash and not force:
            self.storage.append_event(job_id, "stage.skipped", stage.name, f"{stage.display} 已有有效产物，跳过", {})
            return

        manifest["status"] = JobStatus.running.value
        manifest["display_status"] = stage.display
        manifest["stage"] = stage.name
        manifest["overall_progress"] = round((index - 1) / total, 4)
        manifest["stage_progress"] = {"stage": stage.name, "message": stage.display}
        manifest["last_heartbeat_at"] = utc_now_iso()
        stage_run = {
            "stage": stage.name,
            "status": "running",
            "started_at": utc_now_iso(),
            "input_hash": input_hash,
            "command": list(stage.command or []),
        }
        manifest.setdefault("stage_runs", {})[stage.name] = stage_run
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(job_id, "stage.started", stage.name, stage.display, {"dry_run": self.settings.dry_run})

        if self.settings.dry_run:
            self._dry_run_stage(job_id, stage, index=index, total=total)
            return

        if stage.command is not None:
            self._execute_command(job_id, stage)

        manifest = self.storage.read_manifest(job_id)
        stage_run = manifest.setdefault("stage_runs", {}).setdefault(stage.name, {})
        stage_run.update(
            {
                "status": "succeeded",
                "finished_at": utc_now_iso(),
                "input_hash": input_hash,
                "returncode": 0,
            }
        )
        manifest["overall_progress"] = round(index / total, 4)
        manifest["last_heartbeat_at"] = utc_now_iso()
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(job_id, "stage.succeeded", stage.name, f"{stage.display} 完成", {})

    def _dry_run_stage(self, job_id: str, stage: PipelineStage, *, index: int = 0, total: int = 1) -> None:
        report_path = self.storage.project_root(job_id) / "qa" / "server-dry-run-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "job_id": job_id,
            "stage": stage.name,
            "would_run": list(stage.command or []),
            "timestamp": utc_now_iso(),
        }
        atomic_write_json(report_path, report)
        manifest = self.storage.read_manifest(job_id)
        stage_run = manifest.setdefault("stage_runs", {}).setdefault(stage.name, {})
        stage_run.update(
            {
                "status": "succeeded",
                "finished_at": utc_now_iso(),
                "returncode": 0,
                "dry_run": True,
            }
        )
        manifest["overall_progress"] = round(index / total, 4) if total else 0.0
        manifest["last_heartbeat_at"] = utc_now_iso()
        self.storage.write_manifest(job_id, manifest)
        self.storage.append_event(job_id, "stage.succeeded", stage.name, f"{stage.display} dry-run 完成", {})

    def _execute_command(self, job_id: str, stage: PipelineStage) -> None:
        assert stage.command is not None
        self._execute_argv(job_id, stage.name, stage.command)

    def _execute_argv(self, job_id: str, stage_name: str, command: tuple[str, ...]) -> None:
        env = os.environ.copy()
        env.setdefault("CASE_VIDEO_DATA_ROOT", str(self.settings.data_root))
        log_path = self.storage.pipeline_log_path(job_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{utc_now_iso()}] stage={stage_name} command={list(command)}\n")
            process = subprocess.Popen(
                list(command),
                cwd=str(self.settings.repo_root),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            started = time.monotonic()
            while process.poll() is None:
                self._check_cancel(job_id, stage_name, process.pid)
                if time.monotonic() - started > self.settings.command_timeout_seconds:
                    self._terminate_process_group(process.pid)
                    raise AppError("stage_timeout", f"stage timed out: {stage_name}", stage=stage_name)
                time.sleep(0.5)
            if process.returncode != 0:
                raise AppError(
                    "internal_error",
                    f"stage failed: {stage_name} returncode={process.returncode}",
                    retryable=True,
                    stage=stage_name,
                )

    def _check_cancel(self, job_id: str, stage: str, pid: int | None = None) -> None:
        manifest = self.storage.read_manifest(job_id)
        if manifest.get("cancel_requested"):
            if pid is not None:
                self._terminate_process_group(pid)
            raise PipelineCanceled(stage)

    def _terminate_process_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        time.sleep(2)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
