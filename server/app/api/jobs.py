from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from server.app.core.errors import AppError
from server.app.models.job import ArtifactInfo, ApprovalMode, CreateJobRequest, InputMode, JobStatus, JobSummary
from server.app.services.contracts import canonical_json
from server.app.services.queue import JobQueue
from server.app.services.storage import JobStorage, StorageError, safe_download_filename, sha256_file, sha256_text
from server.app.services.uploads import UploadStorage


router = APIRouter()
FORBIDDEN_CLIENT_FIELDS = {
    "model",
    "models",
    "provider",
    "base_url",
    "api_key",
    "azure_endpoint",
    "remotion_entry",
}


def get_storage(request: Request) -> JobStorage:
    return request.app.state.storage


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def get_uploads(request: Request) -> UploadStorage:
    return request.app.state.uploads


def public_manifest(manifest: dict[str, Any], queue: JobQueue | None = None) -> dict[str, Any]:
    job_id = manifest["job_id"]
    queue_position = queue.position(job_id) if queue else manifest.get("queue_position")
    payload = {
        "job_id": job_id,
        "job_url": f"/jobs/{job_id}",
        "project_name": manifest["project_name"],
        "manifest_version": manifest.get("manifest_version", 1),
        "input_mode": manifest.get("input_mode", "project"),
        "approval_mode": manifest.get("approval_mode", "editorial"),
        "status": manifest["status"],
        "display_status": manifest.get("display_status", manifest["status"]),
        "stage": manifest.get("stage", "created"),
        "stage_progress": manifest.get("stage_progress", {}),
        "overall_progress": manifest.get("overall_progress", 0.0),
        "queue_position": queue_position,
        "needs_action": manifest.get("needs_action", False),
        "next_action": manifest.get("next_action"),
        "can_approve": manifest.get("can_approve", False),
        "can_retry": manifest.get("can_retry", False),
        "can_cancel": manifest.get("can_cancel", False),
        "created_at": manifest["created_at"],
        "updated_at": manifest["updated_at"],
        "last_heartbeat_at": manifest.get("last_heartbeat_at"),
        "current_revisions": manifest.get("current_revisions", {}),
        "approved_revisions": manifest.get("approved_revisions", {}),
        "budget": manifest.get("budget", {}),
        "invalidations": manifest.get("invalidations", []),
        "model_routes": manifest.get("model_routes", {}),
        "pipeline_stages": _public_pipeline_stages(manifest.get("pipeline_stages", [])),
        "stage_runs": _public_stage_runs(manifest.get("stage_runs", {})),
        "error": _public_error(manifest.get("error")),
        "dry_run": bool(manifest.get("dry_run", False)),
    }
    return JobSummary(**payload).model_dump()


def _public_pipeline_stages(stages: Any) -> list[dict[str, Any]]:
    if not isinstance(stages, list):
        return []
    public: list[dict[str, Any]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        public.append(
            {
                key: stage.get(key)
                for key in ("index", "name", "display", "model_task")
                if stage.get(key) is not None
            }
        )
    return public


def _public_stage_runs(stage_runs: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(stage_runs, dict):
        return {}
    allowed = {
        "stage",
        "display",
        "status",
        "started_at",
        "finished_at",
        "run_count",
        "model_task",
        "dry_run",
        "error_code",
        "message",
    }
    return {
        str(name): {key: value for key, value in run.items() if key in allowed}
        for name, run in stage_runs.items()
        if isinstance(run, dict)
    }


def _public_error(error: Any) -> dict[str, Any] | None:
    if not isinstance(error, dict):
        return None
    return {
        key: error.get(key)
        for key in ("error_id", "stage", "code", "message")
        if error.get(key) is not None
    }


def reject_forbidden_fields(payload: dict[str, Any]) -> None:
    forbidden = sorted(FORBIDDEN_CLIENT_FIELDS.intersection(payload.keys()))
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"client cannot override server model or Remotion settings: {', '.join(forbidden)}",
        )


async def parse_create_request(request: Request) -> tuple[CreateJobRequest, Path | None]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        form_payload = {
            key: value
            for key, value in form.items()
            if key != "project_zip" and not hasattr(value, "filename")
        }
        reject_forbidden_fields(form_payload)
        upload = form.get("project_zip")
        zip_path = None
        if upload is not None and hasattr(upload, "filename"):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix != ".zip":
                raise HTTPException(status_code=400, detail="project_zip must be a .zip file")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as handle:
                size = 0
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > request.app.state.settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="project_zip exceeds max upload size")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                if size == 0:
                    raise HTTPException(status_code=400, detail="project_zip must not be empty")
                zip_path = Path(handle.name)
        try:
            return CreateJobRequest(**form_payload), zip_path
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="request body must be a JSON object")
    reject_forbidden_fields(payload)
    try:
        return CreateJobRequest(**payload), None
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc


@router.get("/v1/jobs")
def list_jobs(
    status: JobStatus | None = None,
    q: str | None = None,
    needs_action: bool | None = None,
    approval_mode: ApprovalMode | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    manifests = storage.list_manifests(
        status=status.value if status else None,
        q=q,
        needs_action=needs_action,
        approval_mode=approval_mode.value if approval_mode else None,
        created_from=created_from,
        created_to=created_to,
    )
    page = manifests[offset:offset + limit]
    return {
        "jobs": [public_manifest(manifest, queue) for manifest in page],
        "total": len(manifests),
        "limit": limit,
        "offset": offset,
    }


@router.post("/v1/jobs", response_model=JobSummary)
async def create_job(
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
    uploads: UploadStorage = Depends(get_uploads),
) -> dict[str, Any]:
    create_request, zip_path = await parse_create_request(request)
    if create_request.input_mode is InputMode.project and zip_path is None and not create_request.seed_project:
        raise HTTPException(
            status_code=400,
            detail="phase A requires project_zip or seed_project with title, narration, and storyboard files",
        )
    if create_request.input_mode is not InputMode.project and zip_path is not None:
        raise HTTPException(status_code=400, detail="project_zip is only accepted in project mode")

    request_payload = create_request.model_dump(mode="json")
    if zip_path is not None:
        request_payload["project_zip_sha256"] = sha256_file(zip_path)
    request_hash = sha256_text(canonical_json(request_payload))
    effective_idempotency_key = idempotency_key or create_request.client_request_id

    try:
        if effective_idempotency_key:
            existing = storage.find_idempotent_job(effective_idempotency_key, request_hash=request_hash)
            if existing:
                return public_manifest(existing, queue)

        if create_request.input_mode is InputMode.source:
            total = 0
            for upload_id in create_request.upload_ids:
                record = uploads.get(upload_id)
                if record["status"] != "complete":
                    raise AppError("upload_incomplete", f"upload is not complete: {upload_id}")
                if record["suffix"] == ".zip":
                    raise AppError("source_invalid", "zip uploads are only accepted in project mode")
                total += int(record["size_bytes"] or 0)
            if total > request.app.state.settings.max_upload_bytes:
                raise AppError("source_invalid", "combined source uploads exceed the configured limit", status_code=413)

        manifest = storage.create_job(
            project_name=create_request.project_name,
            approval_mode=create_request.approval_mode,
            idempotency_key=effective_idempotency_key,
            target_duration=create_request.target_duration,
            seed_project=create_request.seed_project,
            input_mode=create_request.input_mode,
            target_duration_seconds=(
                create_request.target_duration_seconds.model_dump()
                if create_request.target_duration_seconds
                else None
            ),
            program=create_request.program,
            upload_ids=create_request.upload_ids,
            structured_input=create_request.structured_input,
            budget_limit_micros=create_request.budget_limit_micros,
            request_hash=request_hash,
        )
        for upload_id in create_request.upload_ids:
            uploads.bind(upload_id, manifest["job_id"])
        if zip_path is not None:
            storage.extract_project_zip(manifest["job_id"], zip_path)
        manifest = storage.set_queued(manifest["job_id"])
        queue.enqueue(manifest["job_id"])
        return public_manifest(manifest, queue)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if zip_path is not None and zip_path.exists():
            zip_path.unlink()


@router.get("/v1/jobs/{job_id}", response_model=JobSummary)
def get_job(
    job_id: str,
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    try:
        return public_manifest(storage.read_manifest(job_id), queue)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/jobs/{job_id}/events")
def get_events(
    job_id: str,
    request: Request,
    after: int = 0,
    follow: bool = False,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    storage: JobStorage = Depends(get_storage),
) -> Response:
    if last_event_id:
        try:
            after = max(after, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Last-Event-ID must be an integer") from exc
    try:
        events = storage.read_events(job_id, after=after)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if "text/event-stream" in request.headers.get("accept", ""):
        async def generate() -> Any:
            cursor = after
            pending = events
            yield "retry: 2000\n\n"
            idle_ticks = 0
            while True:
                for event in pending:
                    cursor = max(cursor, int(event["seq"]))
                    yield f"id: {event['seq']}\n"
                    yield "event: job-event\n"
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if not follow or await request.is_disconnected():
                    break
                manifest = storage.read_manifest(job_id)
                if manifest.get("status") in {"succeeded", "failed", "canceled"}:
                    break
                await asyncio.sleep(1)
                pending = storage.read_events(job_id, after=cursor)
                idle_ticks += 1
                if not pending and idle_ticks % 10 == 0:
                    yield f": heartbeat {cursor}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return JSONResponse({"events": events})


@router.get("/v1/jobs/{job_id}/artifacts")
def list_artifacts(
    job_id: str,
    storage: JobStorage = Depends(get_storage),
) -> dict[str, list[dict[str, Any]]]:
    try:
        manifest = storage.read_manifest(job_id)
        qa_run = manifest.get("stage_runs", {}).get("qa.execute", {})
        formal_video = (
            manifest.get("status") == "succeeded"
            and qa_run.get("status") == "succeeded"
            and not qa_run.get("dry_run", manifest.get("dry_run", False))
        )
        artifacts = [
            ArtifactInfo(
                **item,
                formal_delivery=formal_video and item.get("kind") == "video",
            ).model_dump()
            for item in storage.list_artifacts(job_id)
        ]
        return {"artifacts": artifacts}
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/jobs/{job_id}/artifacts/{artifact_name:path}")
def download_artifact(
    job_id: str,
    artifact_name: str,
    storage: JobStorage = Depends(get_storage),
) -> FileResponse:
    try:
        path = storage.artifact_path(job_id, artifact_name)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=safe_download_filename(path.name))


@router.post("/v1/jobs/{job_id}/cancel", response_model=JobSummary)
def cancel_job(
    job_id: str,
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    try:
        manifest = storage.request_cancel(job_id)
        return public_manifest(manifest, queue)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/jobs/{job_id}/retry", response_model=JobSummary)
def retry_job(
    job_id: str,
    force: bool = False,
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    try:
        manifest = storage.read_manifest(job_id)
        manifest["cancel_requested"] = False
        if force:
            manifest["force_requested"] = True
        storage.write_manifest(job_id, manifest)
        manifest = storage.set_queued(job_id)
        queue.enqueue(job_id)
        return public_manifest(manifest, queue)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/jobs/{job_id}/approve", response_model=JobSummary)
def approve_job(
    job_id: str,
    storage: JobStorage = Depends(get_storage),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    try:
        manifest = storage.read_manifest(job_id)
        if manifest.get("input_mode") != InputMode.project.value or manifest.get("current_revisions", {}).get("editorial"):
            raise HTTPException(
                status_code=409,
                detail="use the revision-specific editorial or visual-plan approval endpoint",
            )
        if not manifest.get("can_approve"):
            raise HTTPException(status_code=409, detail="job is not waiting for approval")
        manifest["needs_action"] = False
        manifest["can_approve"] = False
        manifest["next_action"] = None
        storage.write_manifest(job_id, manifest)
        storage.append_event(job_id, "job.approved", manifest.get("stage"), "人工审核已通过", {})
        queue.enqueue(job_id)
        return public_manifest(manifest, queue)
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
