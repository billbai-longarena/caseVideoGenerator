from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from server.app.core.config import Settings
from server.app.models.job import ApprovalMode, InputMode, JobStatus, utc_now_iso
from server.app.services.stage_graph import pipeline_catalog
from server.app.services.task_registry import TaskRegistry


def build_job_manifest(
    settings: Settings,
    *,
    project_name: str,
    approval_mode: ApprovalMode | str,
    input_mode: InputMode | str,
    idempotency_key: str | None,
    target_duration: str | None = None,
    target_duration_seconds: dict[str, int] | None = None,
    program: str = "销售不复杂",
    seed_project: str | None = None,
    upload_ids: list[str] | None = None,
    structured_input: dict[str, Any] | None = None,
    budget_limit_micros: int | None = None,
    job_id: str | None = None,
    now: str | None = None,
    task_registry: TaskRegistry | None = None,
) -> dict[str, Any]:
    """Build manifest v2 without touching the filesystem or database."""

    mode = input_mode.value if isinstance(input_mode, InputMode) else str(input_mode)
    approval = approval_mode.value if isinstance(approval_mode, ApprovalMode) else str(approval_mode)
    source_uploads = list(upload_ids or [])
    if mode in {InputMode.source.value, InputMode.structured.value} and target_duration_seconds is None:
        target_duration_seconds = {"min": 240, "max": 420}
    registry = task_registry or TaskRegistry(settings)
    current_time = now or utc_now_iso()
    identifier = job_id or (
        f"job_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )
    return {
        "manifest_version": 2,
        "job_id": identifier,
        "project_name": project_name,
        "input_mode": mode,
        "approval_mode": approval,
        "target_duration": target_duration,
        "target_duration_seconds": target_duration_seconds,
        "program": program,
        "seed_project": seed_project,
        "inputs": {
            "upload_ids": source_uploads,
            "has_structured_input": structured_input is not None,
        },
        "status": JobStatus.created.value,
        "display_status": "已创建",
        "stage": "created",
        "stage_progress": {},
        "overall_progress": 0.0,
        "queue_position": None,
        "needs_action": False,
        "next_action": None,
        "can_approve": False,
        "can_retry": False,
        "can_cancel": True,
        "created_at": current_time,
        "updated_at": current_time,
        "last_heartbeat_at": None,
        "dry_run": settings.dry_run,
        "cancel_requested": False,
        "idempotency_key_hash": (
            hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
            if idempotency_key
            else None
        ),
        "contract_versions": {
            "source_manifest": "v1",
            "case_inputs": "v1",
            "case_model": "v1",
            "editorial": "v1",
            "editorial_review": "v1",
            "visual_plan": "v2",
            "image_prompts": "v2",
            "timeline": "v1",
            "artifact_index": "v1",
        },
        "current_revisions": {
            "case_model": None,
            "editorial": None,
            "visual_plan": None,
        },
        "approved_revisions": {
            "editorial": None,
            "visual_plan": None,
        },
        "approval_checkpoints": {"visual_contract": None},
        "model_routes": settings.public_model_routes(),
        "task_registry": registry.snapshot(),
        "pipeline_stages": pipeline_catalog(),
        "prompt_pins": registry.prompt_pins(),
        "budget": {
            "currency": "USD",
            "limit_micros": budget_limit_micros,
            "spent_micros": 0,
        },
        "stage_runs": {},
        "artifacts": [],
        "artifact_index_sha256": None,
    }
