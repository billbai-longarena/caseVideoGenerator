from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping

from server.app.core.config import Settings
from server.app.core.errors import AppError
from server.app.models.job import utc_now_iso
from server.app.persistence.artifact_commit import ArtifactCommitService, ArtifactSource
from server.app.persistence.object_store import ObjectStore
from server.app.persistence.repository import (
    PhaseCRepository,
    RepositoryConflict,
    RepositoryNotFound,
    sha256_json,
)
from server.app.services.contracts import ContractRegistry, canonical_json
from server.app.services.revisions import (
    CASE_MODEL_INVALIDATES,
    DOMAINS,
    NARRATION_INVALIDATES,
    PROGRAM_CLOSER,
    PROGRAM_OPENER,
    PROHIBITED_CONTRAST,
    SPACED_ACRONYM,
    TITLE_INVALIDATES,
    VISUAL_INVALIDATES,
    RevisionDomain,
    approval_stage,
    http_etag,
    normalize_domain,
    normalize_etag,
)
from server.app.services.streams import queue_for_stage
from server.app.services.visual_adapter import build_rich_storyboard


MAX_REVISION_FILE_BYTES = 16 * 1024 * 1024


class DistributedRevisionService:
    """Immutable, tenant-scoped review revisions backed by DB + object storage."""

    def __init__(
        self,
        settings: Settings,
        repository: PhaseCRepository,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store
        self.committer = ArtifactCommitService(repository, object_store)
        self.contracts = ContractRegistry(settings.repo_root / "server" / "schemas")

    # -- Public read surface -------------------------------------------------

    def list_revisions(self, tenant_id: str, job_id: str, domain: str) -> list[dict[str, Any]]:
        spec = normalize_domain(domain)
        records = self.repository.list_artifact_revisions(tenant_id, job_id, domain=spec.slug)
        revisions = [self._read_revision(record, metadata_only=True)["metadata"] for record in records]
        revisions.sort(key=lambda item: (int(item.get("revision_number", 0)), str(item.get("revision_id", ""))))
        return revisions

    def get_revision(
        self,
        tenant_id: str,
        job_id: str,
        domain: str,
        revision_id: str,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        try:
            record = self.repository.get_artifact_revision(tenant_id, revision_id)
        except RepositoryNotFound as exc:
            raise AppError("not_found", "revision not found") from exc
        if record["job_id"] != job_id or record["domain"] != spec.slug:
            raise AppError("not_found", "revision not found")
        return self._read_revision(record)

    def current_review(self, tenant_id: str, job_id: str, domain: str) -> dict[str, Any]:
        spec = normalize_domain(domain)
        job = self.repository.get_job(tenant_id, job_id)
        revision_id = job.get("current_revisions", {}).get(spec.manifest_key)
        if not revision_id:
            raise AppError("approval_required", f"no current {spec.slug} revision exists")
        revision = self.get_revision(tenant_id, job_id, spec.slug, str(revision_id))
        metadata = revision["metadata"]
        approved = job.get("approved_revisions", {}).get(spec.manifest_key)
        blockers = self._blockers(spec, revision["files"])
        decision = job.get("review_decisions", {}).get(spec.manifest_key, {})
        rejected = decision.get("revision") == revision_id and decision.get("action") == "rejected"
        supports_approval = spec.slug in {"editorial", "visual-plan"}
        payload: dict[str, Any] = {
            "job_id": job_id,
            "domain": spec.slug,
            "revision": revision_id,
            "etag": http_etag(str(metadata["etag"])),
            "approved_revision": approved,
            "is_approved": approved == revision_id,
            "is_rejected": rejected,
            "can_approve": supports_approval and not blockers and approved != revision_id and not rejected,
            "blockers": blockers,
            "metadata": metadata,
            "files": revision["files"],
        }
        if spec.slug == "visual-plan":
            payload["scene_context"] = self._visual_scene_context(
                tenant_id,
                job_id,
                revision,
            )
        return payload

    def get_model_revision_request(
        self,
        tenant_id: str,
        job_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        job = self.repository.get_job(tenant_id, job_id)
        requests = job.get("model_revision_requests", {})
        if not isinstance(requests, Mapping):
            requests = {}
        record = requests.get(request_id)
        if not isinstance(record, Mapping):
            raise AppError("not_found", "model revision request not found")

        request_hash = str(record.get("request_hash") or "")
        stage = str(record.get("stage") or "")
        matching_runs = [
            run
            for run in self.repository.list_stage_runs(tenant_id, job_id)
            if run.get("stage") == stage and run.get("input_hash") == request_hash
        ]
        latest_run = matching_runs[-1] if matching_runs else None
        persisted_status = str(record.get("status") or "")
        status = persisted_status
        if persisted_status != "succeeded" and latest_run is not None:
            status = str(latest_run.get("status") or persisted_status or "queued")
        if not status:
            status = "queued"

        error = None
        if latest_run and (latest_run.get("error_code") or latest_run.get("error_message")):
            error = {
                "code": latest_run.get("error_code"),
                "message": latest_run.get("error_message"),
            }
        completed_at = record.get("completed_at")
        if completed_at is None and latest_run and status in {
            "succeeded",
            "failed",
            "dead_letter",
            "canceled",
            "superseded",
        }:
            completed_at = latest_run.get("finished_at")

        return {
            "request_id": str(record.get("request_id") or request_id),
            "domain": record.get("domain"),
            "base_revision": record.get("base_revision"),
            "task": record.get("task"),
            "stage": stage,
            "status": status,
            "outcome": record.get("outcome"),
            "result_revision": record.get("result_revision"),
            "stage_run_id": record.get("stage_run_id") or (latest_run or {}).get("stage_run_id"),
            "created_at": record.get("created_at"),
            "started_at": record.get("started_at") or (latest_run or {}).get("started_at"),
            "completed_at": completed_at,
            "error": error,
        }

    # -- Revision creation ---------------------------------------------------

    def create_case_model(
        self,
        tenant_id: str,
        job_id: str,
        case_model: dict[str, Any],
        *,
        change_summary: str,
        actor: str,
        author_type: str = "model",
        model_run_id: str | None = None,
        input_hash: str | None = None,
        base_revision: str | None = None,
        if_match: str | None = None,
        enforce_concurrency: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self.contracts.validate("case_model", "v1", case_model)
        return self._create_revision(
            tenant_id,
            job_id,
            DOMAINS["case-model"],
            {"case_model.json": case_model},
            change_summary=change_summary,
            actor=actor,
            author_type=author_type,
            model_run_id=model_run_id,
            input_hash=input_hash,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=enforce_concurrency,
            request_id=request_id,
        )

    def create_editorial(
        self,
        tenant_id: str,
        job_id: str,
        *,
        title: str,
        narration: str,
        change_summary: str,
        actor: str,
        author_type: str = "human",
        review: dict[str, Any] | None = None,
        model_run_id: str | None = None,
        input_hash: str | None = None,
        base_revision: str | None = None,
        if_match: str | None = None,
        enforce_concurrency: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        clean_title = title.strip()
        clean_narration = narration.strip()
        editorial = {
            "version": "1",
            "title": clean_title,
            "narration": clean_narration,
            "change_summary": change_summary,
        }
        self.contracts.validate("editorial", "v1", editorial, error_code="request_invalid")
        merged_review = self.review_editorial(tenant_id, job_id, clean_title, clean_narration, review)
        self.contracts.validate("editorial_review", "v1", merged_review)
        return self._create_revision(
            tenant_id,
            job_id,
            DOMAINS["editorial"],
            {
                "title.txt": clean_title + "\n",
                "narration.txt": clean_narration + "\n",
                "review.json": merged_review,
            },
            change_summary=change_summary,
            actor=actor,
            author_type=author_type,
            model_run_id=model_run_id,
            input_hash=input_hash,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=enforce_concurrency,
            request_id=request_id,
        )

    def create_visual_plan(
        self,
        tenant_id: str,
        job_id: str,
        *,
        plan: dict[str, Any],
        change_summary: str,
        actor: str,
        rich_storyboard: dict[str, Any] | None = None,
        image_prompts: dict[str, Any] | None = None,
        readiness: dict[str, Any] | None = None,
        author_type: str = "human",
        model_run_id: str | None = None,
        input_hash: str | None = None,
        base_revision: str | None = None,
        if_match: str | None = None,
        enforce_concurrency: bool = True,
        invalidate_stage_runs: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        plan_version = str(plan.get("version", ""))
        if plan_version not in {"1", "2"}:
            raise AppError("request_invalid", f"unsupported visual plan version: {plan_version or 'missing'}")
        self.contracts.validate("visual_plan", f"v{plan_version}", plan, error_code="request_invalid")
        server_readiness = self.review_visual_plan(tenant_id, job_id, plan)
        if readiness:
            server_readiness["client_observations"] = copy.deepcopy(readiness)
        prompts = image_prompts or {"version": plan_version, "prompts": []}
        prompt_version = str(prompts.get("version", ""))
        if prompt_version not in {"1", "2"}:
            raise AppError("request_invalid", f"unsupported image prompt version: {prompt_version or 'missing'}")
        self.contracts.validate("image_prompts", f"v{prompt_version}", prompts, error_code="request_invalid")

        if server_readiness["blockers"]:
            storyboard = rich_storyboard or {
                "status": "blocked",
                "sourcePlanVersion": plan_version,
                "scenes": [],
            }
        elif rich_storyboard is not None:
            storyboard = copy.deepcopy(rich_storyboard)
        else:
            timeline = self._current_json_file(tenant_id, job_id, "narration.timeline.json")
            if timeline is None:
                raise AppError("readiness_blocked", "narration.timeline.json is required to compile a visual plan")
            job = self.repository.get_job(tenant_id, job_id)
            editorial_id = job.get("current_revisions", {}).get("editorial")
            if not editorial_id:
                raise AppError("readiness_blocked", "an editorial revision is required to compile a visual plan")
            editorial = self.get_revision(tenant_id, job_id, "editorial", str(editorial_id))
            authored_title = str(editorial["files"]["title.txt"]).strip()
            try:
                storyboard = build_rich_storyboard(
                    plan,
                    timeline,
                    authored_title=authored_title,
                    project_name=str(job["project_name"]),
                    program=str(job.get("program", "销售不复杂")),
                    image_prompts=prompts,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise AppError("readiness_blocked", str(exc)) from exc

        return self._create_revision(
            tenant_id,
            job_id,
            DOMAINS["visual-plan"],
            {
                "storyboard_plan.json": plan,
                "rich_storyboard.json": storyboard,
                "image_prompts.json": prompts,
                "readiness.json": server_readiness,
            },
            change_summary=change_summary,
            actor=actor,
            author_type=author_type,
            model_run_id=model_run_id,
            input_hash=input_hash,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=enforce_concurrency,
            invalidate_stage_runs=invalidate_stage_runs,
            request_id=request_id,
        )

    def request_model_revision(
        self,
        tenant_id: str,
        job_id: str,
        domain: str,
        *,
        base_revision: str,
        if_match: str,
        feedback: str,
        issues: list[dict[str, Any]],
        change_summary: str,
        actor: str,
        scene_ids: list[str] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist feedback and enqueue the pinned Claude revision task.

        Provider calls never run in the API process. The planning worker loads
        this request by input hash and executes the task pinned in the manifest.
        """

        spec = normalize_domain(domain)
        if spec.slug == "editorial":
            stage = "editorial.rewrite"
            task = "narration.rewrite"
        elif spec.slug == "visual-plan":
            stage = "visual.repair"
            task = "remotion.repair"
        else:
            raise AppError("request_invalid", f"{spec.slug} does not support model revision")

        job = self.repository.get_job(tenant_id, job_id)
        self._assert_current_concurrency(
            tenant_id,
            job_id,
            spec,
            base_revision,
            if_match,
            job=job,
        )
        task_snapshot = job.get("task_registry", {}).get(task)
        if not isinstance(task_snapshot, dict):
            raise AppError("model_task_unregistered", f"model task is not pinned: {task}")
        if (
            task_snapshot.get("provider") != "azure_anthropic"
            or task_snapshot.get("model") != "salesnail-cs-46"
            or task_snapshot.get("transport") != "anthropic_messages"
        ):
            raise AppError("model_route_missing", f"model task has an invalid pinned route: {task}")

        revision_request_id = f"mrev_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "request_id": revision_request_id,
            "domain": spec.slug,
            "base_revision": base_revision,
            "feedback": feedback.strip(),
            "issues": copy.deepcopy(issues),
            "scene_ids": list(scene_ids or []),
            "change_summary": change_summary.strip(),
            "actor": actor,
            "task": task,
            "stage": stage,
            "created_at": utc_now_iso(),
        }
        request_hash = sha256_json(
            {
                "domain": spec.slug,
                "base_revision": base_revision,
                "feedback": record["feedback"],
                "issues": record["issues"],
                "scene_ids": record["scene_ids"],
                "change_summary": record["change_summary"],
                "task": task,
            }
        )
        record["request_hash"] = request_hash
        try:
            return self.repository.enqueue_revision_request(
                tenant_id,
                job_id,
                domain=spec.slug,
                manifest_key=spec.manifest_key,
                base_revision=base_revision,
                request_record=record,
                request_hash=request_hash,
                stage=stage,
                queue_name=queue_for_stage(stage),
                route_snapshot_hash=sha256_json(task_snapshot),
                config_snapshot_hash=sha256_json(
                    {
                        "manifest_version": job.get("manifest_version"),
                        "contract_versions": job.get("contract_versions", {}),
                        "prompt_pin": job.get("prompt_pins", {}).get(task),
                        "task": task_snapshot,
                    }
                ),
                expected_job_version=int(job["row_version"]),
                actor_id=actor,
                request_id=request_id,
            )
        except RepositoryConflict as exc:
            self._raise_conflict(tenant_id, job_id, spec)
            raise exc  # pragma: no cover

    # -- Approval decisions --------------------------------------------------

    def approve(
        self,
        tenant_id: str,
        job_id: str,
        domain: str,
        *,
        revision_id: str,
        base_revision: str,
        if_match: str,
        has_unsaved_draft: bool,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        if spec.slug not in {"editorial", "visual-plan"}:
            raise AppError("request_invalid", f"{spec.slug} does not have an approval gate")
        if has_unsaved_draft:
            raise AppError("approval_required", "save or discard the unsaved draft before approval")
        job = self.repository.get_job(tenant_id, job_id)
        revision = self._assert_current_concurrency(
            tenant_id,
            job_id,
            spec,
            base_revision,
            if_match,
            job=job,
        )
        if revision_id != base_revision:
            self._raise_conflict(tenant_id, job_id, spec, job=job)
        blockers = self._blockers(spec, revision["files"])
        if blockers:
            raise AppError(
                "approval_required",
                f"{spec.slug} has blocking review issues",
                public_details={"blockers": blockers},
            )
        if job.get("approved_revisions", {}).get(spec.manifest_key) == revision_id:
            return {"job": job, "stage_run": None, "reused": True}

        manifest = self._manifest_for_update(job)
        contract_gate = spec.slug == "visual-plan" and manifest.get("stage") == "visual.contract-approval"
        gate = "visual-contract" if contract_gate else spec.slug
        next_stage = (
            "tts.generate"
            if spec.slug == "editorial"
            else "assets.generate"
            if contract_gate
            else "render.prepare"
        )
        manifest.setdefault("approved_revisions", {})[spec.manifest_key] = revision_id
        if contract_gate:
            manifest.setdefault("approval_checkpoints", {})["visual_contract"] = revision_id
        manifest.setdefault("review_decisions", {})[spec.manifest_key] = {
            "revision": revision_id,
            "action": "approved",
            "actor": actor,
            "created_at": utc_now_iso(),
        }
        manifest.update(
            {
                "status": "queued",
                "display_status": "已批准，等待继续处理",
                "stage": next_stage,
                "needs_action": False,
                "can_approve": False,
                "next_action": None,
                "updated_at": utc_now_iso(),
            }
        )
        hashes = self._stage_hashes(manifest, next_stage, revision_id)
        try:
            return self.repository.decide_revision(
                tenant_id,
                job_id,
                domain=spec.slug,
                manifest_key=spec.manifest_key,
                gate=gate,
                revision_id=revision_id,
                decision="approved",
                actor_id=actor,
                reason=reason,
                manifest=manifest,
                expected_job_version=int(job["row_version"]),
                event_type=f"{spec.slug}.approved",
                event_stage="visual.contract-approval" if contract_gate else approval_stage(spec),
                event_message=f"{spec.slug} 版本 {revision_id} 已批准",
                event_payload={"revision": revision_id, "next_stage": next_stage},
                next_stage=next_stage,
                queue_name=queue_for_stage(next_stage),
                stage_input_hash=hashes["input"],
                route_snapshot_hash=hashes["route"],
                config_snapshot_hash=hashes["config"],
                priority="interactive",
                request_id=request_id,
            )
        except RepositoryConflict as exc:
            self._raise_conflict(tenant_id, job_id, spec)
            raise exc  # pragma: no cover - _raise_conflict always raises

    def reject(
        self,
        tenant_id: str,
        job_id: str,
        domain: str,
        *,
        revision_id: str,
        base_revision: str,
        if_match: str,
        actor: str,
        reason: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        if spec.slug not in {"editorial", "visual-plan"}:
            raise AppError("request_invalid", f"{spec.slug} does not have an approval gate")
        job = self.repository.get_job(tenant_id, job_id)
        self._assert_current_concurrency(
            tenant_id,
            job_id,
            spec,
            base_revision,
            if_match,
            job=job,
        )
        if revision_id != base_revision:
            self._raise_conflict(tenant_id, job_id, spec, job=job)
        decision = job.get("review_decisions", {}).get(spec.manifest_key, {})
        if decision.get("revision") == revision_id and decision.get("action") == "rejected":
            return {"job": job, "stage_run": None, "reused": True}

        manifest = self._manifest_for_update(job)
        manifest.setdefault("approved_revisions", {})[spec.manifest_key] = None
        manifest.setdefault("review_decisions", {})[spec.manifest_key] = {
            "revision": revision_id,
            "action": "rejected",
            "actor": actor,
            "created_at": utc_now_iso(),
        }
        manifest.update(
            {
                "status": "waiting_approval",
                "display_status": "审核已驳回",
                "stage": approval_stage(spec),
                "needs_action": True,
                "can_approve": False,
                "next_action": "修改内容或提交模型修订",
                "updated_at": utc_now_iso(),
            }
        )
        try:
            return self.repository.decide_revision(
                tenant_id,
                job_id,
                domain=spec.slug,
                manifest_key=spec.manifest_key,
                gate=spec.slug,
                revision_id=revision_id,
                decision="rejected",
                actor_id=actor,
                reason=reason,
                manifest=manifest,
                expected_job_version=int(job["row_version"]),
                event_type=f"{spec.slug}.rejected",
                event_stage=approval_stage(spec),
                event_message=f"{spec.slug} 版本 {revision_id} 已驳回",
                event_payload={"revision": revision_id, "reason": reason},
                request_id=request_id,
            )
        except RepositoryConflict as exc:
            self._raise_conflict(tenant_id, job_id, spec)
            raise exc  # pragma: no cover

    # -- History operations --------------------------------------------------

    def restore(
        self,
        tenant_id: str,
        job_id: str,
        domain: str,
        target_revision: str,
        *,
        base_revision: str,
        if_match: str,
        change_summary: str,
        actor: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        target = self.get_revision(tenant_id, job_id, spec.slug, target_revision)
        files = target["files"]
        summary = f"{change_summary}（来源 {target_revision}）"
        if spec.slug == "editorial":
            return self.create_editorial(
                tenant_id,
                job_id,
                title=str(files["title.txt"]).strip(),
                narration=str(files["narration.txt"]).strip(),
                change_summary=summary,
                author_type="restore",
                actor=actor,
                base_revision=base_revision,
                if_match=if_match,
                request_id=request_id,
            )
        if spec.slug == "visual-plan":
            return self.create_visual_plan(
                tenant_id,
                job_id,
                plan=files["storyboard_plan.json"],
                rich_storyboard=files.get("rich_storyboard.json"),
                image_prompts=files.get("image_prompts.json"),
                change_summary=summary,
                author_type="restore",
                actor=actor,
                base_revision=base_revision,
                if_match=if_match,
                request_id=request_id,
            )
        return self.create_case_model(
            tenant_id,
            job_id,
            files["case_model.json"],
            change_summary=summary,
            author_type="restore",
            actor=actor,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=True,
            request_id=request_id,
        )

    def diff(
        self,
        tenant_id: str,
        job_id: str,
        domain: str,
        from_revision: str,
        to_revision: str,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        before = self.get_revision(tenant_id, job_id, spec.slug, from_revision)
        after = self.get_revision(tenant_id, job_id, spec.slug, to_revision)
        file_diffs: dict[str, str] = {}
        for name in spec.files:
            left_text = self._diff_text(before["files"].get(name))
            right_text = self._diff_text(after["files"].get(name))
            file_diffs[name] = "".join(
                difflib.unified_diff(
                    left_text.splitlines(keepends=True),
                    right_text.splitlines(keepends=True),
                    fromfile=f"{from_revision}/{name}",
                    tofile=f"{to_revision}/{name}",
                )
            )
        return {
            "domain": spec.slug,
            "from_revision": from_revision,
            "to_revision": to_revision,
            "files": file_diffs,
        }

    # -- Deterministic review ------------------------------------------------

    def review_editorial(
        self,
        tenant_id: str,
        job_id: str,
        title: str,
        narration: str,
        model_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self.repository.get_job(tenant_id, job_id)
        issues: list[dict[str, Any]] = []

        def add(severity: str, category: str, message: str, suggestion: str, auto_fixable: bool) -> None:
            issue_id = "lint-" + hashlib.sha256(f"{category}:{message}".encode("utf-8")).hexdigest()[:12]
            issues.append(
                {
                    "issue_id": issue_id,
                    "severity": severity,
                    "category": category,
                    "message": message,
                    "evidence_refs": [],
                    "suggestion": suggestion,
                    "auto_fixable": auto_fixable,
                }
            )

        if not title.strip() or "\n" in title or "\r" in title:
            add("blocker", "title_hook", "标题必须是恰好一行的非空文本。", "删除换行并保留一个明确标题。", True)
        if title.strip().startswith(("\"", "'", "“", "‘")) or title.strip().endswith(("\"", "'", "”", "’")):
            add("blocker", "title_hook", "标题不应带首尾引号。", "移除标题外围引号。", True)
        if re.match(r"^销售不复杂\s*[:：|｜—-]", title.strip()):
            add("blocker", "title_hook", "标题不应重复栏目名前缀。", "只保留案例标题。", True)
        if PROGRAM_OPENER not in narration:
            add("blocker", "other", "旁白缺少固定栏目开场。", "补入销售不复杂固定开场。", True)
        if PROGRAM_CLOSER not in narration:
            add("blocker", "other", "旁白缺少固定栏目结尾。", "补入销售不复杂固定结尾。", True)
        combined = f"{title}\n{narration}"
        if PROHIBITED_CONTRAST.search(combined):
            add("blocker", "prohibited_pattern", "文稿包含禁用的‘不是……而是……’近似结构。", "改为直接陈述或因果句。", True)
        if SPACED_ACRONYM.search(combined):
            add("blocker", "acronym_spacing", "业务 acronym 被拆成了带空格的字母。", "将 CEO、CIO、CRM、ERP、SKU 等保持连续。", True)
        if re.search(r"\d", narration):
            add("warning", "numeric_readout", "旁白含阿拉伯数字，生成 TTS 前必须确认中文读法。", "保留屏幕数字，并在 TTS 正规化文本中明确读法。", True)
        target = manifest.get("target_duration_seconds")
        if isinstance(target, dict) and isinstance(target.get("min"), int) and isinstance(target.get("max"), int):
            estimated_seconds = max(1, round(len(re.sub(r"\s+", "", narration)) / 4.0))
            if estimated_seconds < target["min"] or estimated_seconds > target["max"]:
                add(
                    "blocker",
                    "duration",
                    f"估算旁白时长约 {estimated_seconds} 秒，不在 {target['min']}–{target['max']} 秒目标范围内。",
                    "通过增删旁白内容调整时长，再用真实 TTS timeline 复核。",
                    True,
                )
        if model_review:
            self.contracts.validate("editorial_review", "v1", model_review)
            existing = {item["issue_id"] for item in issues}
            for issue in model_review.get("issues", []):
                candidate = copy.deepcopy(issue)
                if candidate["issue_id"] in existing:
                    candidate["issue_id"] = "model-" + hashlib.sha256(
                        canonical_json(candidate).encode("utf-8")
                    ).hexdigest()[:12]
                existing.add(candidate["issue_id"])
                issues.append(candidate)
        verdict = "blocked" if any(item["severity"] == "blocker" for item in issues) else "revise" if issues else "pass"
        return {
            "version": "1",
            "verdict": verdict,
            "issues": issues,
            "summary": f"确定性检查与独立审查共发现 {len(issues)} 个问题。" if issues else "确定性检查与独立审查均通过。",
        }

    def review_visual_plan(self, tenant_id: str, job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        manifest = self.repository.get_job(tenant_id, job_id)
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        def blocker(code: str, message: str) -> None:
            blockers.append({"code": code, "message": message})

        editorial_id = manifest.get("current_revisions", {}).get("editorial")
        if editorial_id:
            editorial = self.get_revision(tenant_id, job_id, "editorial", str(editorial_id))
            title = str(editorial["files"].get("title.txt", "")).strip()
            if plan.get("cover", {}).get("title") != title:
                blocker("cover_title_mismatch", "封面标题必须与当前 title.txt 完全一致。")
        else:
            blocker("editorial_missing", "生成视觉计划前必须存在当前文稿版本。")
        program = str(manifest.get("program", "销售不复杂"))
        subtitle_label = plan.get("subtitleLabel")
        if subtitle_label != program or "\n" in str(subtitle_label):
            blocker("subtitle_label_invalid", f"subtitleLabel 必须为单行“{program}”。")

        plan_version = str(plan.get("version", "1"))
        scenes = plan.get("scenes", [])
        expected_start = 1 if plan_version == "2" else 0
        seen_scene_ids: set[str] = set()
        for scene in scenes:
            scene_id = str(scene["id"] if plan_version == "2" else scene["scene_id"])
            if scene_id in seen_scene_ids:
                blocker("duplicate_scene_id", f"scene id {scene_id} 重复。")
            seen_scene_ids.add(scene_id)
            if plan_version == "2":
                at_unit, end_unit = int(scene["units"][0]), int(scene["units"][1])
            else:
                at_unit = int(scene["atUnit"])
                end_unit = at_unit + int(scene["units"]) - 1
            if at_unit > expected_start:
                blocker("unit_gap", f"{scene_id} 前存在 narration unit 空档。")
            elif at_unit < expected_start:
                blocker("unit_overlap", f"{scene_id} 与前一场景的 narration unit 重叠。")
            expected_start = max(expected_start, end_unit + 1)

        unit_count = self._timeline_unit_count(tenant_id, job_id)
        expected_end = unit_count + 1 if plan_version == "2" and unit_count is not None else unit_count
        if expected_end is not None and expected_start != expected_end:
            covered = expected_start - 1 if plan_version == "2" else expected_start
            blocker("unit_coverage", f"场景覆盖到 unit {covered}，timeline 共 {unit_count} 个 unit。")
        elif unit_count is None:
            warnings.append({"code": "timeline_pending", "message": "timeline 尚未生成，当前仅校验场景内部 unit 连续性。"})
        if plan_version == "2":
            image_count = len(plan.get("assets", []))
            for asset in plan.get("assets", []):
                if asset.get("sceneId") not in seen_scene_ids:
                    blocker("asset_scene_missing", f"资产 {asset.get('id')} 指向不存在的场景。")
        else:
            image_count = sum(1 for scene in scenes if not scene.get("reuse") and not scene.get("allowBackgroundReuse"))
        return {
            "version": plan_version,
            "status": "blocked" if blockers else "ready",
            "blockers": blockers,
            "warnings": warnings,
            "estimated_image_count": image_count,
            "checked_at": utc_now_iso(),
        }

    # -- Internal helpers ----------------------------------------------------

    def _create_revision(
        self,
        tenant_id: str,
        job_id: str,
        spec: RevisionDomain,
        files: dict[str, Any],
        *,
        change_summary: str,
        actor: str,
        author_type: str,
        model_run_id: str | None,
        input_hash: str | None,
        base_revision: str | None,
        if_match: str | None,
        enforce_concurrency: bool,
        request_id: str | None,
        invalidate_stage_runs: bool = True,
    ) -> dict[str, Any]:
        job = self.repository.get_job(tenant_id, job_id)
        current_id = job.get("current_revisions", {}).get(spec.manifest_key)
        current: dict[str, Any] | None = None
        if current_id:
            current = self.get_revision(tenant_id, job_id, spec.slug, str(current_id))
        if enforce_concurrency:
            self._assert_concurrency(
                tenant_id,
                job_id,
                spec,
                base_revision,
                if_match,
                current_metadata=current["metadata"] if current else None,
                job=job,
            )

        encoded_files = self._encode_files(files)
        content_hashes = {
            name: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for name, value in encoded_files.items()
        }
        content_sha256 = hashlib.sha256(canonical_json(content_hashes).encode("utf-8")).hexdigest()
        if current and current["metadata"].get("content_sha256") == content_sha256:
            return {**current, "reused": True}

        revisions = self.repository.list_artifact_revisions(tenant_id, job_id, domain=spec.slug)
        revision_number = len(revisions) + 1
        revision_id = f"{spec.prefix}{revision_number:04d}-{uuid.uuid4().hex[:8]}"
        parent_sha = current["metadata"].get("content_sha256") if current else None
        metadata = {
            "metadata_version": 1,
            "domain": spec.slug,
            "revision_id": revision_id,
            "revision_number": revision_number,
            "parent_revision": current_id,
            "author_type": author_type,
            "actor": actor,
            "created_at": utc_now_iso(),
            "input_hash": input_hash
            or hashlib.sha256(
                canonical_json({"parent": parent_sha, "files": content_hashes}).encode("utf-8")
            ).hexdigest(),
            "model_run_id": model_run_id,
            "prompt_versions": copy.deepcopy(job.get("prompt_pins", {})),
            "schema_versions": copy.deepcopy(job.get("contract_versions", {})),
            "content_hashes": content_hashes,
            "content_sha256": content_sha256,
            "etag": content_sha256,
            "change_summary": change_summary,
        }
        changes = self._revision_changes(spec, current, files)
        manifest = self._manifest_for_update(job)
        if manifest.get("current_revisions", {}).get(spec.manifest_key) != current_id:
            self._raise_conflict(tenant_id, job_id, spec, job=job)
        manifest.setdefault("current_revisions", {})[spec.manifest_key] = revision_id
        invalidated = self._apply_invalidation(
            manifest,
            spec,
            revision_id,
            changes,
            files,
            invalidate_stage_runs=invalidate_stage_runs,
        )
        manifest["updated_at"] = utc_now_iso()

        with tempfile.TemporaryDirectory(prefix=f"casevideo-{revision_id}-") as temporary:
            root = Path(temporary)
            sources: list[ArtifactSource] = []
            for name, value in {**encoded_files, "metadata.json": self._encode_json(metadata)}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
                sources.append(ArtifactSource(logical_name=name, path=path))
            try:
                self.committer.commit(
                    tenant_id=tenant_id,
                    job_id=job_id,
                    domain=spec.slug,
                    revision_id=revision_id,
                    parent_id=str(current_id) if current_id else None,
                    sources=sources,
                    created_by=actor,
                    make_current=True,
                    manifest=manifest,
                    expected_job_version=int(job["row_version"]),
                    invalidated_stages=tuple(sorted(invalidated)),
                    event={
                        "event_type": f"revision.{spec.slug}.created",
                        "stage": manifest.get("stage"),
                        "message": f"已创建 {spec.slug} 版本 {revision_id}",
                        "payload": {
                            "domain": spec.slug,
                            "revision": revision_id,
                            "parent_revision": current_id,
                            "changes": changes,
                        },
                    },
                    audit={
                        "actor_id": actor,
                        "action": "revision.create",
                        "resource_type": "artifact_revision",
                        "resource_id": revision_id,
                        "request_id": request_id,
                        "payload": {"job_id": job_id, "domain": spec.slug, "changes": changes},
                    },
                )
            except RepositoryConflict as exc:
                self._raise_conflict(tenant_id, job_id, spec)
                raise exc  # pragma: no cover
        return {"metadata": metadata, "files": copy.deepcopy(files), "reused": False}

    def _read_revision(self, record: Mapping[str, Any], *, metadata_only: bool = False) -> dict[str, Any]:
        blobs = {str(item["logical_name"]): item for item in record.get("artifacts", [])}
        metadata_blob = blobs.get("metadata.json")
        if metadata_blob is None:
            raise AppError("artifact_corrupt", "revision metadata is missing")
        metadata = self._read_json_blob(metadata_blob)
        if metadata.get("revision_id") != record.get("revision_id") or metadata.get("domain") != record.get("domain"):
            raise AppError("artifact_corrupt", "revision metadata does not match its database record")
        if metadata_only:
            return {"metadata": metadata, "files": {}}
        spec = normalize_domain(str(record["domain"]))
        files: dict[str, Any] = {}
        for name in spec.files:
            blob = blobs.get(name)
            if blob is None:
                continue
            raw = self._read_blob(blob)
            try:
                files[name] = json.loads(raw.decode("utf-8")) if name.endswith(".json") else raw.decode("utf-8")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AppError("artifact_corrupt", f"revision file is invalid: {name}") from exc
        return {"metadata": metadata, "files": files}

    def _read_blob(self, blob: Mapping[str, Any]) -> bytes:
        expected_size = int(blob["size_bytes"])
        if expected_size < 0 or expected_size > MAX_REVISION_FILE_BYTES:
            raise AppError("artifact_corrupt", "revision file exceeds the allowed size")
        with self.object_store.open(str(blob["object_key"])) as handle:
            raw = handle.read(expected_size + 1)
        if len(raw) != expected_size:
            raise AppError("artifact_corrupt", "revision file size does not match metadata")
        if hashlib.sha256(raw).hexdigest() != blob["sha256"]:
            raise AppError("artifact_corrupt", "revision file checksum does not match metadata")
        return raw

    def _read_json_blob(self, blob: Mapping[str, Any]) -> dict[str, Any]:
        try:
            payload = json.loads(self._read_blob(blob).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppError("artifact_corrupt", "revision metadata is invalid") from exc
        if not isinstance(payload, dict):
            raise AppError("artifact_corrupt", "revision metadata must be an object")
        return payload

    def _assert_current_concurrency(
        self,
        tenant_id: str,
        job_id: str,
        spec: RevisionDomain,
        base_revision: str | None,
        if_match: str | None,
        *,
        job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_job = job or self.repository.get_job(tenant_id, job_id)
        current_id = current_job.get("current_revisions", {}).get(spec.manifest_key)
        if not current_id:
            self._raise_conflict(tenant_id, job_id, spec, job=current_job)
        revision = self.get_revision(tenant_id, job_id, spec.slug, str(current_id))
        self._assert_concurrency(
            tenant_id,
            job_id,
            spec,
            base_revision,
            if_match,
            current_metadata=revision["metadata"],
            job=current_job,
        )
        return revision

    def _assert_concurrency(
        self,
        tenant_id: str,
        job_id: str,
        spec: RevisionDomain,
        base_revision: str | None,
        if_match: str | None,
        *,
        current_metadata: Mapping[str, Any] | None,
        job: dict[str, Any],
    ) -> None:
        current_id = job.get("current_revisions", {}).get(spec.manifest_key)
        current_etag = current_metadata.get("etag") if current_metadata else None
        if base_revision != current_id or normalize_etag(if_match) != current_etag:
            self._raise_conflict(
                tenant_id,
                job_id,
                spec,
                job=job,
                current_metadata=current_metadata,
            )

    def _raise_conflict(
        self,
        tenant_id: str,
        job_id: str,
        spec: RevisionDomain,
        *,
        job: dict[str, Any] | None = None,
        current_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        current_job = job or self.repository.get_job(tenant_id, job_id)
        current_id = current_job.get("current_revisions", {}).get(spec.manifest_key)
        if current_id and current_metadata is None:
            current_metadata = self.get_revision(tenant_id, job_id, spec.slug, str(current_id))["metadata"]
        current_etag = http_etag(str(current_metadata["etag"])) if current_metadata else None
        raise AppError(
            "revision_conflict",
            "the revision changed on the server; reload and merge before saving",
            action_url=f"/v1/jobs/{job_id}/reviews/{spec.slug}",
            public_details={
                "current_revision": current_id,
                "current_etag": current_etag,
                "reload_url": f"/v1/jobs/{job_id}/reviews/{spec.slug}",
            },
        )

    @staticmethod
    def _manifest_for_update(job: Mapping[str, Any]) -> dict[str, Any]:
        manifest = copy.deepcopy(dict(job))
        for key in ("row_version", "snapshot_sequence", "database_manifest_sha256", "phase_c_snapshot"):
            manifest.pop(key, None)
        return manifest

    def _revision_changes(
        self,
        spec: RevisionDomain,
        current: dict[str, Any] | None,
        new_files: dict[str, Any],
    ) -> list[str]:
        if current is None:
            return ["initial"]
        previous = current["files"]
        if spec.slug == "editorial":
            changes: list[str] = []
            if str(previous.get("title.txt", "")).strip() != str(new_files.get("title.txt", "")).strip():
                changes.append("title")
            if str(previous.get("narration.txt", "")).strip() != str(new_files.get("narration.txt", "")).strip():
                changes.append("narration")
            if previous.get("review.json") != new_files.get("review.json"):
                changes.append("review")
            return changes
        return [spec.slug]

    def _apply_invalidation(
        self,
        manifest: dict[str, Any],
        spec: RevisionDomain,
        revision_id: str,
        changes: list[str],
        files: dict[str, Any],
        *,
        invalidate_stage_runs: bool,
    ) -> set[str]:
        invalidated: set[str] = set()
        if spec.slug == "editorial":
            manifest.setdefault("approved_revisions", {})["editorial"] = None
            manifest.setdefault("review_decisions", {})["editorial"] = {
                "revision": revision_id,
                "action": "pending",
                "created_at": utc_now_iso(),
            }
            if "narration" in changes or "initial" in changes:
                invalidated.update(NARRATION_INVALIDATES)
            elif "title" in changes:
                invalidated.update(TITLE_INVALIDATES)
            if {"title", "narration", "initial"} & set(changes):
                manifest.setdefault("approved_revisions", {})["visual_plan"] = None
                manifest.setdefault("approval_checkpoints", {})["visual_contract"] = None
            blockers = self._blockers(spec, files)
            manifest.update(
                {
                    "status": "waiting_approval",
                    "display_status": "等待文稿审核",
                    "stage": "editorial.approval",
                    "needs_action": True,
                    "can_approve": not blockers,
                    "next_action": "处理文稿 blocker" if blockers else "审核并批准标题与旁白",
                }
            )
        elif spec.slug == "visual-plan":
            manifest.setdefault("approved_revisions", {})["visual_plan"] = None
            if invalidate_stage_runs:
                manifest.setdefault("approval_checkpoints", {})["visual_contract"] = None
            manifest.setdefault("review_decisions", {})["visual_plan"] = {
                "revision": revision_id,
                "action": "pending",
                "created_at": utc_now_iso(),
            }
            invalidated.update(VISUAL_INVALIDATES)
            if manifest.get("approval_mode") == "full":
                blockers = self._blockers(spec, files)
                manifest.update(
                    {
                        "status": "waiting_approval",
                        "display_status": "等待视觉计划审核",
                        "stage": "visual.approval",
                        "needs_action": True,
                        "can_approve": not blockers,
                        "next_action": "处理视觉计划 blocker" if blockers else "审核并批准视觉计划",
                    }
                )
        elif spec.slug == "case-model":
            invalidated.update(CASE_MODEL_INVALIDATES)
            manifest.setdefault("approved_revisions", {})["editorial"] = None
            manifest.setdefault("approved_revisions", {})["visual_plan"] = None
            manifest.setdefault("approval_checkpoints", {})["visual_contract"] = None
        if not invalidate_stage_runs:
            invalidated.clear()
        now = utc_now_iso()
        for stage in sorted(invalidated):
            run = manifest.setdefault("stage_runs", {}).get(stage)
            if run:
                run.update(
                    {
                        "status": "invalidated",
                        "invalidated_at": now,
                        "invalidated_by_revision": revision_id,
                    }
                )
        if invalidated:
            manifest.setdefault("invalidations", []).append(
                {
                    "revision": revision_id,
                    "domain": spec.slug,
                    "changes": changes,
                    "stages": sorted(invalidated),
                    "created_at": now,
                }
            )
        return invalidated

    @staticmethod
    def _blockers(spec: RevisionDomain, files: Mapping[str, Any]) -> list[dict[str, Any]]:
        if spec.slug == "editorial":
            review = files.get("review.json", {})
            return [item for item in review.get("issues", []) if item.get("severity") == "blocker"]
        if spec.slug == "visual-plan":
            return list(files.get("readiness.json", {}).get("blockers", []))
        return []

    def _current_json_file(self, tenant_id: str, job_id: str, logical_name: str) -> dict[str, Any] | None:
        project_name = logical_name.removeprefix("project/")
        accepted_names = {project_name, f"project/{project_name}"}
        for blob in self.repository.list_job_artifacts(tenant_id, job_id, current_only=True):
            if blob.get("logical_name") not in accepted_names:
                continue
            try:
                payload = json.loads(self._read_blob(blob).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AppError("artifact_corrupt", f"artifact is invalid JSON: {logical_name}") from exc
            if not isinstance(payload, dict):
                raise AppError("artifact_corrupt", f"artifact must be an object: {logical_name}")
            return payload
        return None

    def _timeline_unit_count(self, tenant_id: str, job_id: str) -> int | None:
        timeline = self._current_json_file(tenant_id, job_id, "narration.timeline.json")
        if timeline is None:
            return None
        for key in ("units", "narration_units", "items"):
            value = timeline.get(key)
            if isinstance(value, list):
                return len(value)
        value = timeline.get("unit_count")
        return value if isinstance(value, int) and value >= 0 else None

    def _visual_scene_context(
        self,
        tenant_id: str,
        job_id: str,
        revision: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        del tenant_id, job_id
        plan = revision["files"].get("storyboard_plan.json", {})
        version = str(plan.get("version", "")) if isinstance(plan, dict) else ""
        assets_by_scene: dict[str, list[str]] = {}
        if version == "2":
            for asset in plan.get("assets", []):
                if isinstance(asset, dict) and asset.get("sceneId") and asset.get("id"):
                    assets_by_scene.setdefault(str(asset["sceneId"]), []).append(str(asset["id"]))
        context: list[dict[str, Any]] = []
        for scene in plan.get("scenes", []) if isinstance(plan, dict) else []:
            if not isinstance(scene, dict):
                continue
            if version == "2":
                scene_id = str(scene.get("id", ""))
                unit_range = scene.get("units", [])
                if not isinstance(unit_range, list) or len(unit_range) != 2:
                    continue
                first_unit, last_unit = int(unit_range[0]), int(unit_range[1])
                assets = assets_by_scene.get(scene_id, [])
            else:
                scene_id = str(scene.get("scene_id", ""))
                first_unit = int(scene.get("atUnit", 0)) + 1
                last_unit = int(scene.get("atUnit", 0)) + int(scene.get("units", 0))
                assets = [scene_id] if scene_id else []
            context.append(
                {
                    "scene_id": scene_id,
                    "first_unit": first_unit,
                    "last_unit": last_unit,
                    "duration_seconds": None,
                    "preview_url": None,
                    "background_source": "pending",
                    "changed": False,
                    "asset_count": len(assets),
                    "directorial_intent": scene.get("directorialIntent"),
                }
            )
        return context

    @staticmethod
    def _stage_hashes(manifest: Mapping[str, Any], stage: str, revision_id: str) -> dict[str, str]:
        return {
            "input": sha256_json({"stage": stage, "revision": revision_id}),
            "route": sha256_json(manifest.get("model_routes", {})),
            "config": sha256_json(
                {
                    "manifest_version": manifest.get("manifest_version"),
                    "contract_versions": manifest.get("contract_versions", {}),
                    "prompt_pins": manifest.get("prompt_pins", {}),
                    "task_registry": manifest.get("task_registry", {}),
                }
            ),
        }

    @staticmethod
    def _encode_files(files: Mapping[str, Any]) -> dict[str, str]:
        return {
            name: DistributedRevisionService._encode_json(value)
            if isinstance(value, (dict, list))
            else str(value)
            for name, value in files.items()
        }

    @staticmethod
    def _encode_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @staticmethod
    def _diff_text(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return DistributedRevisionService._encode_json(value)
        return str(value or "")
