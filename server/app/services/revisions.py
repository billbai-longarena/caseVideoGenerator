from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from server.app.core.errors import AppError
from server.app.models.job import JobStatus, utc_now_iso
from server.app.services.contracts import canonical_json
from server.app.services.model_gateway import ModelGateway
from server.app.services.visual_adapter import scene_image_path
from server.app.services.storage import (
    JobStorage,
    atomic_copy_file,
    atomic_write_json,
    atomic_write_text,
    exclusive_file_lock,
    sha256_text,
)
from server.app.services.visual_adapter import build_rich_storyboard


PROGRAM_OPENER = "这里是销售不复杂，用销售和管理经典案例帮您揭开销售的秘密。"
PROGRAM_CLOSER = "这期的《销售不复杂》就到这里。帮你揭开销售的魔法秘密，让销售不再复杂。我们下期再见。"
SPACED_ACRONYM = re.compile(r"(?<![A-Z])(?:[A-Z]\s+){1,}[A-Z](?![A-Z])")
PROHIBITED_CONTRAST = re.compile(r"不(?:是|在于).{0,80}(?:而是|而在于)", re.DOTALL)


@dataclass(frozen=True)
class RevisionDomain:
    slug: str
    manifest_key: str
    prefix: str
    files: tuple[str, ...]


DOMAINS: dict[str, RevisionDomain] = {
    "case-model": RevisionDomain("case-model", "case_model", "case-r", ("case_model.json",)),
    "editorial": RevisionDomain(
        "editorial",
        "editorial",
        "editorial-r",
        ("title.txt", "narration.txt", "review.json"),
    ),
    "visual-plan": RevisionDomain(
        "visual-plan",
        "visual_plan",
        "visual-r",
        ("storyboard_plan.json", "rich_storyboard.json", "image_prompts.json", "readiness.json"),
    ),
}

DOMAIN_ALIASES = {
    "case_model": "case-model",
    "visual_plan": "visual-plan",
}

TITLE_INVALIDATES = (
    "visual.plan",
    "visual.build",
    "visual.repair",
    "visual.contract-approval",
    "assets.generate",
    "visual.preview",
    "visual.intent-review",
    "visual.approval",
    "render.prepare",
    "render.execute",
    "qa.execute",
    "delivery.finalize",
)
NARRATION_INVALIDATES = (
    "editorial.approval",
    "tts.generate",
    "visual.plan",
    "visual.build",
    "visual.repair",
    "visual.contract-approval",
    "assets.generate",
    "visual.preview",
    "visual.intent-review",
    "visual.approval",
    "render.prepare",
    "render.execute",
    "qa.execute",
    "delivery.finalize",
)
VISUAL_INVALIDATES = (
    "visual.contract-approval",
    "assets.generate",
    "visual.preview",
    "visual.intent-review",
    "visual.approval",
    "render.prepare",
    "render.execute",
    "qa.execute",
    "delivery.finalize",
)
CASE_MODEL_INVALIDATES = (
    "editorial.compose",
    "editorial.lint",
    "editorial.review",
    "editorial.rewrite",
    *NARRATION_INVALIDATES,
)


def normalize_domain(value: str) -> RevisionDomain:
    slug = DOMAIN_ALIASES.get(value, value)
    try:
        return DOMAINS[slug]
    except KeyError as exc:
        raise AppError("request_invalid", f"unsupported revision domain: {value}") from exc


def http_etag(value: str) -> str:
    return f'"{value}"'


def normalize_etag(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if token.startswith("W/"):
        token = token[2:].strip()
    if len(token) >= 2 and token[0] == token[-1] == '"':
        token = token[1:-1]
    return token


def approval_stage(spec: RevisionDomain) -> str:
    return "visual.approval" if spec.slug == "visual-plan" else "editorial.approval"


class RevisionService:
    def __init__(
        self,
        storage: JobStorage,
        model_gateway: ModelGateway | None = None,
        *,
        revision_namespace: str | None = None,
    ) -> None:
        self.storage = storage
        self.gateway = model_gateway
        self.contracts = storage.contracts
        if revision_namespace is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,31}", revision_namespace):
            raise ValueError("revision_namespace must be a 3-32 character lowercase slug")
        self.revision_namespace = revision_namespace

    def _revision_pattern(self, spec: RevisionDomain, *, capture_number: bool = False) -> re.Pattern[str]:
        digits = r"(\d{4,})" if capture_number else r"\d{4,}"
        # Distributed workers emit job-namespaced revision IDs, while browser
        # edits and restores committed by DistributedRevisionService use an
        # eight-character hexadecimal nonce. Existing unsuffixed single-node
        # revisions remain readable during migration. Keep the accepted forms
        # explicit so a revision ID can never become an arbitrary path name.
        suffix_variants = [r"[0-9a-f]{8}"]
        if self.revision_namespace:
            suffix_variants.insert(0, re.escape(self.revision_namespace))
        suffix = rf"(?:-(?:{'|'.join(suffix_variants)}))?"
        return re.compile(re.escape(spec.prefix) + digits + suffix)

    def _revision_id(self, spec: RevisionDomain, revision_number: int) -> str:
        base = f"{spec.prefix}{revision_number:04d}"
        return f"{base}-{self.revision_namespace}" if self.revision_namespace else base

    def revision_root(self, job_id: str, domain: RevisionDomain) -> Path:
        return self.storage.job_root(job_id) / "revisions" / domain.slug

    def revision_path(self, job_id: str, domain: str, revision_id: str) -> Path:
        spec = normalize_domain(domain)
        if not self._revision_pattern(spec).fullmatch(revision_id):
            raise AppError("request_invalid", f"invalid revision id for {spec.slug}: {revision_id}")
        path = self.revision_root(job_id, spec) / revision_id
        if not path.is_dir():
            raise AppError("not_found", f"revision not found: {revision_id}")
        return path

    def list_revisions(self, job_id: str, domain: str) -> list[dict[str, Any]]:
        spec = normalize_domain(domain)
        self.storage.read_manifest(job_id)
        revisions: list[dict[str, Any]] = []
        for path in sorted(self.revision_root(job_id, spec).glob(f"{spec.prefix}*")):
            metadata_path = path / "metadata.json"
            if not path.is_dir() or not metadata_path.is_file():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            revisions.append(metadata)
        revisions.sort(key=lambda item: item["revision_number"])
        return revisions

    def get_revision(self, job_id: str, domain: str, revision_id: str) -> dict[str, Any]:
        spec = normalize_domain(domain)
        path = self.revision_path(job_id, spec.slug, revision_id)
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        files: dict[str, Any] = {}
        for name in spec.files:
            file_path = path / name
            if not file_path.is_file():
                continue
            if file_path.suffix == ".json":
                files[name] = json.loads(file_path.read_text(encoding="utf-8"))
            else:
                files[name] = file_path.read_text(encoding="utf-8")
        return {"metadata": metadata, "files": files}

    def current_review(self, job_id: str, domain: str) -> dict[str, Any]:
        spec = normalize_domain(domain)
        manifest = self.storage.read_manifest(job_id)
        revision_id = manifest.get("current_revisions", {}).get(spec.manifest_key)
        if not revision_id:
            raise AppError("approval_required", f"no current {spec.slug} revision exists")
        revision = self.get_revision(job_id, spec.slug, revision_id)
        metadata = revision["metadata"]
        approved = manifest.get("approved_revisions", {}).get(spec.manifest_key)
        blockers = self._blockers(spec, revision["files"])
        decision = manifest.get("review_decisions", {}).get(spec.manifest_key, {})
        is_rejected = decision.get("revision") == revision_id and decision.get("action") == "rejected"
        supports_approval = spec.slug in {"editorial", "visual-plan"}
        payload = {
            "job_id": job_id,
            "domain": spec.slug,
            "revision": revision_id,
            "etag": http_etag(metadata["etag"]),
            "approved_revision": approved,
            "is_approved": approved == revision_id,
            "is_rejected": is_rejected,
            "can_approve": supports_approval and not blockers and approved != revision_id and not is_rejected,
            "blockers": blockers,
            "metadata": metadata,
            "files": revision["files"],
        }
        if spec.slug == "visual-plan":
            payload["scene_context"] = self._visual_scene_context(job_id, revision)
        return payload

    def _visual_scene_context(self, job_id: str, revision: dict[str, Any]) -> list[dict[str, Any]]:
        plan = revision["files"].get("storyboard_plan.json", {})
        scenes = plan.get("scenes", []) if isinstance(plan, dict) else []
        plan_version = str(plan.get("version", "")) if isinstance(plan, dict) else ""
        timeline_path = self.storage.project_root(job_id) / "narration.timeline.json"
        timeline_units: dict[int, dict[str, Any]] = {}
        if timeline_path.is_file():
            try:
                timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
                timeline_units = {
                    int(unit["index"]): unit
                    for unit in timeline.get("units", [])
                    if isinstance(unit, dict) and isinstance(unit.get("index"), int)
                }
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                timeline_units = {}

        prompts = revision["files"].get("image_prompts.json", {}).get("prompts", [])
        prompts_by_id = {
            str(item.get("asset_id") or item.get("scene_id")): item
            for item in prompts
            if isinstance(item, dict) and (item.get("asset_id") or item.get("scene_id"))
        }
        assets_by_scene: dict[str, list[str]] = {}
        if plan_version == "2":
            for asset in plan.get("assets", []):
                if not isinstance(asset, dict):
                    continue
                scene_id = str(asset.get("sceneId", ""))
                asset_id = str(asset.get("id", ""))
                if scene_id and asset_id:
                    assets_by_scene.setdefault(scene_id, []).append(asset_id)
        changed_scene_ids: set[str] = set()
        parent_revision = revision["metadata"].get("parent_revision")
        if parent_revision:
            try:
                parent_plan = self.get_revision(job_id, "visual-plan", parent_revision)["files"].get(
                    "storyboard_plan.json", {}
                )
                parent_version = str(parent_plan.get("version", ""))
                parent_id_key = "id" if parent_version == "2" else "scene_id"
                current_id_key = "id" if plan_version == "2" else "scene_id"
                parent_scenes = {
                    str(item.get(parent_id_key)): item
                    for item in parent_plan.get("scenes", [])
                    if isinstance(item, dict) and item.get(parent_id_key)
                }
                for scene in scenes:
                    if isinstance(scene, dict) and parent_scenes.get(str(scene.get(current_id_key))) != scene:
                        changed_scene_ids.add(str(scene.get(current_id_key)))
            except AppError:
                changed_scene_ids = set()

        context: list[dict[str, Any]] = []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            if plan_version == "2":
                scene_id = str(scene.get("id", ""))
                unit_range = scene.get("units", [])
                if not isinstance(unit_range, list) or len(unit_range) != 2:
                    continue
                first_index = int(unit_range[0])
                last_index = int(unit_range[1])
                scene_assets = assets_by_scene.get(scene_id, [])
                preview_asset_id = scene_assets[0] if scene_assets else ""
            else:
                scene_id = str(scene.get("scene_id", ""))
                at_unit = int(scene.get("atUnit", 0))
                unit_count = int(scene.get("units", 0))
                first_index = at_unit + 1
                last_index = at_unit + unit_count
                scene_assets = [scene_id]
                preview_asset_id = scene_id
            first_unit = timeline_units.get(first_index, {})
            last_unit = timeline_units.get(last_index, {})
            start = first_unit.get("start")
            end = last_unit.get("end")
            duration = None
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                duration = max(0.0, round(float(end) - float(start), 3))
            relative = scene_image_path(preview_asset_id) if preview_asset_id else ""
            preview_path = self.storage.project_root(job_id) / relative
            preview_url = None
            if relative and preview_path.is_file():
                encoded = "/".join(quote(part, safe="") for part in ("project/" + relative).split("/"))
                preview_url = f"/v1/jobs/{quote(job_id, safe='')}/artifacts/{encoded}"
            prompt = prompts_by_id.get(preview_asset_id, {})
            context.append(
                {
                    "scene_id": scene_id,
                    "first_unit": first_index,
                    "last_unit": last_index,
                    "duration_seconds": duration,
                    "preview_url": preview_url,
                    "style_family": prompt.get("style_family"),
                    "background_source": "generated" if preview_url else "pending",
                    "changed": scene_id in changed_scene_ids,
                    "asset_count": len(scene_assets),
                    "directorial_intent": scene.get("directorialIntent"),
                }
            )
        return context

    def create_case_model(
        self,
        job_id: str,
        case_model: dict[str, Any],
        *,
        change_summary: str,
        author_type: str = "model",
        actor: str = "system",
        model_run_id: str | None = None,
        input_hash: str | None = None,
        base_revision: str | None = None,
        if_match: str | None = None,
        enforce_concurrency: bool = False,
    ) -> dict[str, Any]:
        self.contracts.validate("case_model", "v1", case_model)
        return self._create_revision(
            job_id,
            DOMAINS["case-model"],
            {"case_model.json": case_model},
            change_summary=change_summary,
            author_type=author_type,
            actor=actor,
            model_run_id=model_run_id,
            input_hash=input_hash,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=enforce_concurrency,
        )

    def create_editorial(
        self,
        job_id: str,
        *,
        title: str,
        narration: str,
        change_summary: str,
        author_type: str = "human",
        actor: str = "user",
        review: dict[str, Any] | None = None,
        model_run_id: str | None = None,
        input_hash: str | None = None,
        base_revision: str | None = None,
        if_match: str | None = None,
        enforce_concurrency: bool = True,
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
        merged_review = self.review_editorial(job_id, clean_title, clean_narration, review)
        self.contracts.validate("editorial_review", "v1", merged_review)
        return self._create_revision(
            job_id,
            DOMAINS["editorial"],
            {
                "title.txt": clean_title + "\n",
                "narration.txt": clean_narration + "\n",
                "review.json": merged_review,
            },
            change_summary=change_summary,
            author_type=author_type,
            actor=actor,
            model_run_id=model_run_id,
            input_hash=input_hash,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=enforce_concurrency,
        )

    def create_editorial_model_revision(
        self,
        job_id: str,
        *,
        base_revision: str,
        if_match: str,
        feedback: str,
        issues: list[dict[str, Any]],
        change_summary: str,
        actor: str,
    ) -> dict[str, Any]:
        if self.gateway is None:
            raise AppError("model_route_unavailable", "model gateway is not configured")
        current = self.current_review(job_id, "editorial")
        self._assert_concurrency(
            job_id,
            DOMAINS["editorial"],
            base_revision,
            if_match,
            current_metadata=current["metadata"],
        )
        title = str(current["files"]["title.txt"]).strip()
        narration = str(current["files"]["narration.txt"]).strip()
        output = self.gateway.run_json(
            "narration.rewrite",
            "v1",
            {
                "task": "narration.rewrite",
                "context": {
                    "title": title,
                    "narration": narration,
                    "feedback": feedback,
                    "project_name": self.storage.read_manifest(job_id)["project_name"],
                },
                "issues": issues,
                "constraints": {"program": "销售不复杂", "preserve_supported_facts": True},
            },
            job_id=job_id,
        )
        independent_review = self.gateway.run_json(
            "editorial.review",
            "v1",
            {
                "task": "editorial.review",
                "context": {
                    "title": output["title"],
                    "narration": output["narration"],
                    "project_name": self.storage.read_manifest(job_id)["project_name"],
                },
                "issues": [],
                "constraints": {"independent_review": True},
            },
            job_id=job_id,
        )
        return self.create_editorial(
            job_id,
            title=output["title"],
            narration=output["narration"],
            change_summary=change_summary or output.get("change_summary", "模型修订"),
            author_type="model",
            actor=actor,
            review=independent_review,
            input_hash=sha256_text(canonical_json({"feedback": feedback, "issues": issues})),
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=True,
        )

    def create_visual_plan(
        self,
        job_id: str,
        *,
        plan: dict[str, Any],
        change_summary: str,
        rich_storyboard: dict[str, Any] | None = None,
        image_prompts: dict[str, Any] | None = None,
        readiness: dict[str, Any] | None = None,
        author_type: str = "human",
        actor: str = "user",
        model_run_id: str | None = None,
        input_hash: str | None = None,
        base_revision: str | None = None,
        if_match: str | None = None,
        enforce_concurrency: bool = True,
        invalidate_stage_runs: bool = True,
    ) -> dict[str, Any]:
        plan_version = str(plan.get("version", ""))
        if plan_version not in {"1", "2"}:
            raise AppError("request_invalid", f"unsupported visual plan version: {plan_version or 'missing'}")
        self.contracts.validate("visual_plan", f"v{plan_version}", plan, error_code="request_invalid")
        server_readiness = self.review_visual_plan(job_id, plan)
        if readiness:
            server_readiness["client_observations"] = readiness
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
        else:
            manifest = self.storage.read_manifest(job_id)
            timeline_path = self.storage.project_root(job_id) / "narration.timeline.json"
            if not timeline_path.is_file():
                raise AppError("readiness_blocked", "narration.timeline.json is required to compile a visual plan")
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            editorial_id = manifest.get("current_revisions", {}).get("editorial")
            if not editorial_id:
                raise AppError("readiness_blocked", "an editorial revision is required to compile a visual plan")
            editorial = self.get_revision(job_id, "editorial", editorial_id)
            authored_title = str(editorial["files"]["title.txt"]).strip()
            try:
                storyboard = build_rich_storyboard(
                    plan,
                    timeline,
                    authored_title=authored_title,
                    project_name=manifest["project_name"],
                    program=manifest.get("program", "销售不复杂"),
                    image_prompts=prompts,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise AppError("readiness_blocked", str(exc)) from exc
        return self._create_revision(
            job_id,
            DOMAINS["visual-plan"],
            {
                "storyboard_plan.json": plan,
                "rich_storyboard.json": storyboard,
                "image_prompts.json": prompts,
                "readiness.json": server_readiness,
            },
            change_summary=change_summary,
            author_type=author_type,
            actor=actor,
            model_run_id=model_run_id,
            input_hash=input_hash,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=enforce_concurrency,
            invalidate_stage_runs=invalidate_stage_runs,
        )

    def create_visual_model_revision(
        self,
        job_id: str,
        *,
        base_revision: str,
        if_match: str,
        feedback: str,
        issues: list[dict[str, Any]],
        scene_ids: list[str],
        change_summary: str,
        actor: str,
    ) -> dict[str, Any]:
        if self.gateway is None:
            raise AppError("model_route_unavailable", "model gateway is not configured")
        current = self.current_review(job_id, "visual-plan")
        self._assert_concurrency(
            job_id,
            DOMAINS["visual-plan"],
            base_revision,
            if_match,
            current_metadata=current["metadata"],
        )
        current_plan = current["files"]["storyboard_plan.json"]
        readiness = current["files"].get("readiness.json", {})
        unit_count = self._timeline_unit_count(job_id)
        if unit_count is None:
            if str(current_plan.get("version")) == "2":
                unit_count = max(
                    (
                        int(scene.get("units", [1, 1])[1])
                        for scene in current_plan.get("scenes", [])
                        if isinstance(scene, dict)
                    ),
                    default=1,
                )
            else:
                unit_count = max(
                    (
                        int(scene.get("atUnit", 0)) + int(scene.get("units", 0))
                        for scene in current_plan.get("scenes", [])
                        if isinstance(scene, dict)
                    ),
                    default=1,
                )
        repair_issues = [*issues]
        repair_issues.append(
            {
                "code": "reviewer_feedback",
                "message": feedback,
                "scene_ids": scene_ids,
            }
        )
        output = self.gateway.run_json(
            "remotion.repair",
            "v2",
            {
                "task": "remotion.repair",
                "context": {
                    "visual_plan": current_plan,
                    "readiness": readiness,
                    "feedback": feedback,
                    "scene_ids": scene_ids,
                    "project_name": self.storage.read_manifest(job_id)["project_name"],
                    "title": current_plan.get("cover", {}).get("title", ""),
                    "unit_count": unit_count,
                },
                "issues": repair_issues,
                "constraints": {
                    "timeline_is_authoritative": True,
                    "preserve_approved_editorial": True,
                    "subtitle_label": "销售不复杂",
                    "unit_anchor_base": 1,
                    "preserve_explicit_director_controls": True,
                },
            },
            job_id=job_id,
        )
        return self.create_visual_plan(
            job_id,
            plan=output,
            image_prompts={"version": "2", "prompts": []},
            change_summary=change_summary,
            author_type="model",
            actor=actor,
            input_hash=sha256_text(
                canonical_json(
                    {
                        "feedback": feedback,
                        "issues": issues,
                        "scene_ids": scene_ids,
                    }
                )
            ),
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=True,
        )

    def approve(
        self,
        job_id: str,
        domain: str,
        *,
        revision_id: str,
        base_revision: str,
        if_match: str,
        has_unsaved_draft: bool,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        if spec.slug not in {"editorial", "visual-plan"}:
            raise AppError("request_invalid", f"{spec.slug} does not have an approval gate")
        if has_unsaved_draft:
            raise AppError("approval_required", "save or discard the unsaved draft before approval")
        approval_event_stage = approval_stage(spec)
        lock = self.storage.job_root(job_id) / f".revision-{spec.slug}.lock"
        with exclusive_file_lock(lock):
            manifest = self.storage.read_manifest(job_id)
            if spec.slug == "visual-plan" and manifest.get("stage") == "visual.contract-approval":
                approval_event_stage = "visual.contract-approval"
            current_id = manifest.get("current_revisions", {}).get(spec.manifest_key)
            if revision_id != base_revision or current_id != revision_id:
                self._raise_conflict(job_id, spec, manifest)
            revision = self.get_revision(job_id, spec.slug, revision_id)
            self._assert_concurrency(
                job_id,
                spec,
                base_revision,
                if_match,
                current_metadata=revision["metadata"],
                manifest=manifest,
            )
            blockers = self._blockers(spec, revision["files"])
            if blockers:
                raise AppError(
                    "approval_required",
                    f"{spec.slug} has blocking review issues",
                    public_details={"blockers": blockers},
                )

            def mutation(current: dict[str, Any]) -> None:
                if current.get("current_revisions", {}).get(spec.manifest_key) != revision_id:
                    self._raise_conflict(job_id, spec, current)
                current.setdefault("approved_revisions", {})[spec.manifest_key] = revision_id
                if spec.slug == "visual-plan" and current.get("stage") == "visual.contract-approval":
                    current.setdefault("approval_checkpoints", {})["visual_contract"] = revision_id
                current.setdefault("review_decisions", {})[spec.manifest_key] = {
                    "revision": revision_id,
                    "action": "approved",
                    "actor": actor,
                    "created_at": utc_now_iso(),
                }
                current["needs_action"] = False
                current["can_approve"] = False
                current["next_action"] = None
                if current.get("status") == JobStatus.waiting_approval.value:
                    current["status"] = JobStatus.queued.value
                    current["display_status"] = "已批准，等待继续处理"

            manifest = self.storage.mutate_manifest(job_id, mutation)
            self._append_approval(job_id, spec, revision_id, "approved", actor, reason)
        self.storage.append_event(
            job_id,
            f"{spec.slug}.approved",
            approval_event_stage,
            f"{spec.slug} 版本 {revision_id} 已批准",
            {"revision": revision_id},
        )
        return manifest

    def reject(
        self,
        job_id: str,
        domain: str,
        *,
        revision_id: str,
        base_revision: str,
        if_match: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        if spec.slug not in {"editorial", "visual-plan"}:
            raise AppError("request_invalid", f"{spec.slug} does not have an approval gate")
        lock = self.storage.job_root(job_id) / f".revision-{spec.slug}.lock"
        with exclusive_file_lock(lock):
            manifest = self.storage.read_manifest(job_id)
            current_id = manifest.get("current_revisions", {}).get(spec.manifest_key)
            if revision_id != base_revision or current_id != revision_id:
                self._raise_conflict(job_id, spec, manifest)
            revision = self.get_revision(job_id, spec.slug, revision_id)
            self._assert_concurrency(
                job_id,
                spec,
                base_revision,
                if_match,
                current_metadata=revision["metadata"],
                manifest=manifest,
            )

            def mutation(current: dict[str, Any]) -> None:
                if current.get("current_revisions", {}).get(spec.manifest_key) != revision_id:
                    self._raise_conflict(job_id, spec, current)
                current.setdefault("approved_revisions", {})[spec.manifest_key] = None
                current.setdefault("review_decisions", {})[spec.manifest_key] = {
                    "revision": revision_id,
                    "action": "rejected",
                    "actor": actor,
                    "created_at": utc_now_iso(),
                }
                current["status"] = JobStatus.waiting_approval.value
                current["display_status"] = "审核已驳回"
                current["stage"] = approval_stage(spec)
                current["needs_action"] = True
                current["can_approve"] = False
                current["next_action"] = "修改内容或提交模型修订"

            manifest = self.storage.mutate_manifest(job_id, mutation)
            self._append_approval(job_id, spec, revision_id, "rejected", actor, reason)
        self.storage.append_event(
            job_id,
            f"{spec.slug}.rejected",
            approval_stage(spec),
            f"{spec.slug} 版本 {revision_id} 已驳回",
            {"revision": revision_id, "reason": reason},
        )
        return manifest

    def restore(
        self,
        job_id: str,
        domain: str,
        target_revision: str,
        *,
        base_revision: str,
        if_match: str,
        change_summary: str,
        actor: str,
    ) -> dict[str, Any]:
        spec = normalize_domain(domain)
        target = self.get_revision(job_id, spec.slug, target_revision)
        files = target["files"]
        summary = f"{change_summary}（来源 {target_revision}）"
        if spec.slug == "editorial":
            return self.create_editorial(
                job_id,
                title=str(files["title.txt"]).strip(),
                narration=str(files["narration.txt"]).strip(),
                change_summary=summary,
                author_type="restore",
                actor=actor,
                base_revision=base_revision,
                if_match=if_match,
                enforce_concurrency=True,
            )
        if spec.slug == "visual-plan":
            return self.create_visual_plan(
                job_id,
                plan=files["storyboard_plan.json"],
                rich_storyboard=files.get("rich_storyboard.json"),
                image_prompts=files.get("image_prompts.json"),
                change_summary=summary,
                author_type="restore",
                actor=actor,
                base_revision=base_revision,
                if_match=if_match,
                enforce_concurrency=True,
            )
        return self.create_case_model(
            job_id,
            files["case_model.json"],
            change_summary=summary,
            author_type="restore",
            actor=actor,
            base_revision=base_revision,
            if_match=if_match,
            enforce_concurrency=True,
        )

    def diff(self, job_id: str, domain: str, from_revision: str, to_revision: str) -> dict[str, Any]:
        spec = normalize_domain(domain)
        before = self.get_revision(job_id, spec.slug, from_revision)
        after = self.get_revision(job_id, spec.slug, to_revision)
        file_diffs: dict[str, str] = {}
        for name in spec.files:
            left = before["files"].get(name)
            right = after["files"].get(name)
            if isinstance(left, (dict, list)):
                left_text = json.dumps(left, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            else:
                left_text = str(left or "")
            if isinstance(right, (dict, list)):
                right_text = json.dumps(right, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            else:
                right_text = str(right or "")
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

    def review_editorial(
        self,
        job_id: str,
        title: str,
        narration: str,
        model_review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        manifest = self.storage.read_manifest(job_id)
        issues: list[dict[str, Any]] = []

        def add(severity: str, category: str, message: str, suggestion: str, auto_fixable: bool) -> None:
            issue_id = "lint-" + sha256_text(f"{category}:{message}")[:12]
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
            spoken_chars = len(re.sub(r"\s+", "", narration))
            estimated_seconds = max(1, round(spoken_chars / 4.0))
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
                candidate = dict(issue)
                if candidate["issue_id"] in existing:
                    candidate["issue_id"] = "model-" + sha256_text(canonical_json(candidate))[:12]
                existing.add(candidate["issue_id"])
                issues.append(candidate)

        verdict = "pass"
        if any(issue["severity"] == "blocker" for issue in issues):
            verdict = "blocked"
        elif issues:
            verdict = "revise"
        return {
            "version": "1",
            "verdict": verdict,
            "issues": issues,
            "summary": (
                f"确定性检查与独立审查共发现 {len(issues)} 个问题。"
                if issues
                else "确定性检查与独立审查均通过。"
            ),
        }

    def review_visual_plan(self, job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        manifest = self.storage.read_manifest(job_id)
        blockers: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        def blocker(code: str, message: str) -> None:
            blockers.append({"code": code, "message": message})

        editorial_id = manifest.get("current_revisions", {}).get("editorial")
        if editorial_id:
            editorial = self.get_revision(job_id, "editorial", editorial_id)
            title = str(editorial["files"].get("title.txt", "")).strip()
            if plan.get("cover", {}).get("title") != title:
                blocker("cover_title_mismatch", "封面标题必须与当前 title.txt 完全一致。")
        else:
            blocker("editorial_missing", "生成视觉计划前必须存在当前文稿版本。")

        program = manifest.get("program", "销售不复杂")
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
                at_unit = int(scene["units"][0])
                end_unit = int(scene["units"][1])
            else:
                at_unit = int(scene["atUnit"])
                end_unit = at_unit + int(scene["units"]) - 1
            if at_unit > expected_start:
                blocker("unit_gap", f"{scene_id} 前存在 narration unit 空档。")
            elif at_unit < expected_start:
                blocker("unit_overlap", f"{scene_id} 与前一场景的 narration unit 重叠。")
            expected_start = max(expected_start, end_unit + 1)

        unit_count = self._timeline_unit_count(job_id)
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
            image_count = sum(
                1
                for scene in scenes
                if not scene.get("reuse") and not scene.get("allowBackgroundReuse")
            )
        return {
            "version": plan_version,
            "status": "blocked" if blockers else "ready",
            "blockers": blockers,
            "warnings": warnings,
            "estimated_image_count": image_count,
            "checked_at": utc_now_iso(),
        }

    def _create_revision(
        self,
        job_id: str,
        spec: RevisionDomain,
        files: dict[str, Any],
        *,
        change_summary: str,
        author_type: str,
        actor: str,
        model_run_id: str | None,
        input_hash: str | None,
        base_revision: str | None,
        if_match: str | None,
        enforce_concurrency: bool,
        invalidate_stage_runs: bool = True,
    ) -> dict[str, Any]:
        lock = self.storage.job_root(job_id) / f".revision-{spec.slug}.lock"
        with exclusive_file_lock(lock):
            manifest = self.storage.read_manifest(job_id)
            current_id = manifest.get("current_revisions", {}).get(spec.manifest_key)
            current_metadata = None
            if current_id:
                current_metadata = self.get_revision(job_id, spec.slug, current_id)["metadata"]
            if enforce_concurrency:
                self._assert_concurrency(
                    job_id,
                    spec,
                    base_revision,
                    if_match,
                    current_metadata=current_metadata,
                    manifest=manifest,
                )

            encoded_files = self._encode_files(files)
            content_hashes = {name: sha256_text(value) for name, value in encoded_files.items()}
            content_sha256 = sha256_text(canonical_json(content_hashes))
            if current_metadata and current_metadata.get("content_sha256") == content_sha256:
                current = self.get_revision(job_id, spec.slug, current_id)
                return {**current, "reused": True}

            revision_number = self._next_revision_number(job_id, spec)
            revision_id = self._revision_id(spec, revision_number)
            parent_sha = current_metadata.get("content_sha256") if current_metadata else None
            metadata = {
                "metadata_version": 1,
                "domain": spec.slug,
                "revision_id": revision_id,
                "revision_number": revision_number,
                "parent_revision": current_id,
                "author_type": author_type,
                "actor": actor,
                "created_at": utc_now_iso(),
                "input_hash": input_hash or sha256_text(canonical_json({"parent": parent_sha, "files": content_hashes})),
                "model_run_id": model_run_id,
                "prompt_versions": manifest.get("prompt_pins", {}),
                "schema_versions": manifest.get("contract_versions", {}),
                "content_hashes": content_hashes,
                "content_sha256": content_sha256,
                "etag": content_sha256,
                "change_summary": change_summary,
            }
            revision_dir = self._write_revision_directory(job_id, spec, revision_id, encoded_files, metadata)
            changes = self._revision_changes(job_id, spec, current_id, files)
            def mutation(current: dict[str, Any]) -> None:
                pointer = current.get("current_revisions", {}).get(spec.manifest_key)
                if pointer != current_id:
                    self._raise_conflict(job_id, spec, current)
                current.setdefault("current_revisions", {})[spec.manifest_key] = revision_id
                self._apply_invalidation(
                    current,
                    spec,
                    revision_id,
                    changes,
                    files,
                    invalidate_stage_runs=invalidate_stage_runs,
                )

            updated_manifest = self.storage.mutate_manifest(job_id, mutation)
            self._materialize(spec, revision_dir, self.storage.project_root(job_id))
        self.storage.append_event(
            job_id,
            f"revision.{spec.slug}.created",
            updated_manifest.get("stage"),
            f"已创建 {spec.slug} 版本 {revision_id}",
            {
                "domain": spec.slug,
                "revision": revision_id,
                "parent_revision": current_id,
                "changes": changes,
            },
        )
        return {"metadata": metadata, "files": files, "reused": False}

    def _write_revision_directory(
        self,
        job_id: str,
        spec: RevisionDomain,
        revision_id: str,
        encoded_files: dict[str, str],
        metadata: dict[str, Any],
    ) -> Path:
        root = self.revision_root(job_id, spec)
        root.mkdir(parents=True, exist_ok=True)
        destination = root / revision_id
        if destination.exists():
            raise AppError("revision_conflict", f"revision already exists: {revision_id}")
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{revision_id}-", dir=str(root)))
        try:
            for name, value in encoded_files.items():
                atomic_write_text(temp_dir / name, value)
            atomic_write_json(temp_dir / "metadata.json", metadata)
            directory_fd = os.open(temp_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            os.replace(temp_dir, destination)
            root_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        return destination

    @staticmethod
    def _encode_files(files: dict[str, Any]) -> dict[str, str]:
        encoded: dict[str, str] = {}
        for name, value in files.items():
            if isinstance(value, (dict, list)):
                encoded[name] = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            else:
                encoded[name] = str(value)
        return encoded

    def _next_revision_number(self, job_id: str, spec: RevisionDomain) -> int:
        maximum = 0
        pattern = self._revision_pattern(spec, capture_number=True)
        for path in self.revision_root(job_id, spec).glob(f"{spec.prefix}*"):
            match = pattern.fullmatch(path.name)
            if match:
                maximum = max(maximum, int(match.group(1)))
        return maximum + 1

    @staticmethod
    def _materialize(spec: RevisionDomain, revision_dir: Path, project_root: Path) -> None:
        project_root.mkdir(parents=True, exist_ok=True)
        for name in spec.files:
            source = revision_dir / name
            if not source.is_file():
                continue
            target_name = name
            if spec.slug == "case-model" and name == "case_model.json":
                target_name = "case_model.json"
            atomic_copy_file(source, project_root / target_name)

    def _assert_concurrency(
        self,
        job_id: str,
        spec: RevisionDomain,
        base_revision: str | None,
        if_match: str | None,
        *,
        current_metadata: dict[str, Any] | None,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        current_manifest = manifest or self.storage.read_manifest(job_id)
        current_id = current_manifest.get("current_revisions", {}).get(spec.manifest_key)
        current_etag = current_metadata.get("etag") if current_metadata else None
        if base_revision != current_id or normalize_etag(if_match) != current_etag:
            self._raise_conflict(job_id, spec, current_manifest, current_metadata=current_metadata)

    def _raise_conflict(
        self,
        job_id: str,
        spec: RevisionDomain,
        manifest: dict[str, Any],
        *,
        current_metadata: dict[str, Any] | None = None,
    ) -> None:
        current_id = manifest.get("current_revisions", {}).get(spec.manifest_key)
        if current_id and current_metadata is None:
            current_metadata = self.get_revision(job_id, spec.slug, current_id)["metadata"]
        current_etag = http_etag(current_metadata["etag"]) if current_metadata else None
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

    def _revision_changes(
        self,
        job_id: str,
        spec: RevisionDomain,
        current_id: str | None,
        new_files: dict[str, Any],
    ) -> list[str]:
        if current_id is None:
            return ["initial"]
        previous = self.get_revision(job_id, spec.slug, current_id)["files"]
        if spec.slug == "editorial":
            changes = []
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
        invalidate_stage_runs: bool = True,
    ) -> None:
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
            if "title" in changes or "narration" in changes or "initial" in changes:
                manifest.setdefault("approved_revisions", {})["visual_plan"] = None
                manifest.setdefault("approval_checkpoints", {})["visual_contract"] = None
            manifest["status"] = JobStatus.waiting_approval.value
            manifest["display_status"] = "等待文稿审核"
            manifest["stage"] = "editorial.approval"
            blockers = self._blockers(spec, files)
            manifest["needs_action"] = True
            manifest["can_approve"] = not blockers
            manifest["next_action"] = "处理文稿 blocker" if blockers else "审核并批准标题与旁白"
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
                manifest["status"] = JobStatus.waiting_approval.value
                manifest["display_status"] = "等待视觉计划审核"
                manifest["stage"] = "visual.approval"
                manifest["needs_action"] = True
                blockers = self._blockers(spec, files)
                manifest["can_approve"] = not blockers
                manifest["next_action"] = "处理视觉计划 blocker" if blockers else "审核并批准视觉计划"
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

    @staticmethod
    def _blockers(spec: RevisionDomain, files: dict[str, Any]) -> list[dict[str, Any]]:
        if spec.slug == "editorial":
            review = files.get("review.json", {})
            return [issue for issue in review.get("issues", []) if issue.get("severity") == "blocker"]
        if spec.slug == "visual-plan":
            return list(files.get("readiness.json", {}).get("blockers", []))
        return []

    def _timeline_unit_count(self, job_id: str) -> int | None:
        path = self.storage.project_root(job_id) / "narration.timeline.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for key in ("units", "narration_units", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        value = payload.get("unit_count")
        return value if isinstance(value, int) and value >= 0 else None

    def _append_approval(
        self,
        job_id: str,
        spec: RevisionDomain,
        revision_id: str,
        action: str,
        actor: str,
        reason: str | None,
    ) -> None:
        path = self.storage.job_root(job_id) / "approvals.jsonl"
        record = {
            "approval_id": f"approval_{uuid.uuid4().hex}",
            "job_id": job_id,
            "gate": spec.slug,
            "revision": revision_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "created_at": utc_now_iso(),
        }
        with exclusive_file_lock(self.storage.job_root(job_id) / ".approvals.lock"):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
