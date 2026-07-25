from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from server.app.core.errors import AppError
from server.app.models.job import CreateJobRequest, CreateUploadRequest, InputMode
from server.app.persistence.object_store import ObjectStoreError, SignedObjectTokenError
from server.app.persistence.repository import (
    TERMINAL_JOB_STATUSES,
    JobInputRegistration,
    PhaseCRepository,
    RepositoryConflict,
    RepositoryNotFound,
    canonical_json,
    new_id,
    sha256_json,
)
from server.app.security.auth import (
    Permission,
    Principal,
    require_permission,
    require_principal,
    require_recent_reauthentication,
)
from server.app.security.browser import issue_csrf_cookie
from server.app.security.uploads import UploadScannerUnavailable
from server.app.services.manifest_factory import build_job_manifest
from server.app.services.uploads import ALLOWED_EXTENSIONS


router = APIRouter()


class GovernanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quotas: dict[str, Any] | None = None
    retention: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None


class MembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(..., min_length=1, max_length=255)
    role: Literal["viewer", "editor", "producer", "admin"]
    email: str | None = Field(None, max_length=320)
    display_name: str | None = Field(None, max_length=200)
    disabled: bool = False


class ProtectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pinned: bool | None = None
    legal_hold: bool | None = None


class RetentionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime | None = None


class PermanentDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(..., min_length=1, max_length=500)


class CancelJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(None, max_length=2000)


class RetryJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str | None = Field(None, min_length=1, max_length=120)


class BudgetDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    resolution: Literal["raise_limit", "reduce_scope"] | None = None
    expected_job_version: int = Field(..., ge=1)
    new_limit_micros: int | None = Field(None, ge=0)
    reduced_scope: dict[str, Any] | None = None
    reason: str | None = Field(None, max_length=2000)


def _repository(request: Request) -> PhaseCRepository:
    return request.app.state.repository


def _public_upload(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result.pop("object_key", None)
    return result


def _public_input(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result.pop("object_key", None)
    return result


def _public_artifact(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result.pop("object_key", None)
    return result


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or None  # type: ignore[return-value]


def _audit(
    request: Request,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    _repository(request).audit(
        principal.tenant_id,
        actor_id=principal.actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result="succeeded",
        request_id=_request_id(request),
        payload=payload,
    )


def _release_upload_quota(repository: PhaseCRepository, tenant_id: str, upload_id: str) -> None:
    for dimension, suffix in (("upload_bytes", "bytes"), ("upload_files", "files")):
        try:
            repository.release_quota(
                tenant_id,
                dimension=dimension,
                reference_id=f"upload:{upload_id}:{suffix}",
            )
        except RepositoryNotFound:
            continue


def _route_readiness(settings: Any) -> dict[str, dict[str, Any]]:
    routes = {
        "narration": settings.narration_route,
        "remotion": settings.remotion_route,
        "general": settings.general_route,
    }
    result: dict[str, dict[str, Any]] = {}
    for name, route in routes.items():
        credential_ready = bool(route.api_key_env and os.getenv(route.api_key_env))
        endpoint_ready = bool(
            route.endpoint if route.provider == "azure_anthropic" else route.base_url
        )
        request_model_ready = bool(route.request_model)
        configured = credential_ready and endpoint_ready and request_model_ready
        result[name] = {
            **route.public_dict(),
            "configured": configured,
            "status": "configured" if configured else "missing_configuration",
        }
    return result


def _retention_days(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


@router.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
def ready(request: Request) -> dict[str, Any]:
    try:
        schema = request.app.state.database.check_schema()
        # Listing an impossible tenant prefix is a read-only dependency probe.
        next(iter(request.app.state.object_store.list("readiness-probe")), None)
    except Exception as exc:
        raise AppError("internal_error", "service dependencies are not ready", status_code=503) from exc
    return {"status": "ready", "schema": schema, "deployment_mode": "distributed"}


@router.get("/v1/capabilities")
def capabilities(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "tenant_id": principal.tenant_id,
        "deployment_mode": "distributed",
        "input_modes": ["source", "structured"],
        "approval_modes": ["editorial", "auto", "full"],
        "upload": {
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_file_bytes": settings.max_upload_bytes,
            "max_files": settings.max_upload_files,
            "ttl_seconds": settings.upload_ttl_seconds,
        },
        "job": {
            "input_modes": ["source", "structured"],
            "approval_modes": ["editorial", "auto", "full"],
            "default_duration_seconds": {"min": 240, "max": 420},
            "program": "销售不复杂",
        },
        "model_routes": settings.public_model_routes(),
        "model_route_readiness": _route_readiness(settings),
        "model_overrides_allowed": False,
        "pipeline_stage_count": 21,
        "object_store": settings.object_store_backend,
        "auth": {
            "mode": settings.auth_mode,
            "csrf_header": settings.csrf_header_name,
        },
    }


@router.get("/v1/session")
def session(request: Request, principal: Principal = Depends(require_principal)) -> dict[str, Any]:
    memberships = _repository(request).memberships_for_subject(principal.subject)
    active_membership = next(
        (item for item in memberships if item["tenant_id"] == principal.tenant_id),
        {},
    )
    web_session = getattr(request.state, "web_session", None)
    session_details: dict[str, Any] | None = None
    if web_session is not None:
        reauthenticated_at = int(getattr(web_session, "reauthenticated_at", 0) or 0)
        session_details = {
            "issued_at": getattr(web_session, "issued_at", None),
            "expires_at": getattr(web_session, "expires_at", None),
            "reauthenticated_at": reauthenticated_at,
            "reauthentication_fresh_until": (
                reauthenticated_at + request.app.state.settings.reauth_max_age_seconds
            ),
        }
    return {
        "actor_id": principal.actor_id,
        "subject": principal.subject,
        "tenant_id": principal.tenant_id,
        "tenant_name": active_membership.get("tenant_name") or principal.tenant_id,
        "role": principal.role,
        "display_name": principal.display_name or active_membership.get("display_name"),
        "email": principal.email or active_membership.get("email"),
        "token_kind": principal.token_kind,
        "permissions": sorted(permission.value for permission in principal.permissions),
        "memberships": memberships,
        "session": session_details,
    }


@router.post("/v1/session/csrf")
def csrf_token(
    request: Request,
    response: Response,
    _: Principal = Depends(require_principal),
) -> dict[str, str]:
    return {"csrf_token": issue_csrf_cookie(request, response)}


@router.post("/v1/uploads", status_code=status.HTTP_201_CREATED)
def create_upload(
    payload: CreateUploadRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.UPLOADS_WRITE)),
) -> dict[str, Any]:
    settings = request.app.state.settings
    repository = _repository(request)
    if payload.size_bytes > settings.max_upload_bytes:
        raise AppError("source_invalid", "upload exceeds the configured size limit", status_code=413)
    active_uploads = repository.list_uploads(
        principal.tenant_id,
        bound=False,
        include_expired=False,
        limit=settings.max_upload_files + 1,
    )
    if len(active_uploads) >= settings.max_upload_files:
        raise AppError("quota_exceeded", "too many unbound uploads")

    upload_id = new_id("upl")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.upload_ttl_seconds)
    reservations: list[tuple[str, str]] = []
    try:
        for dimension, amount, suffix in (
            ("upload_bytes", payload.size_bytes, "bytes"),
            ("upload_files", 1, "files"),
        ):
            reference = f"upload:{upload_id}:{suffix}"
            repository.reserve_quota(
                principal.tenant_id,
                dimension=dimension,
                amount=amount,
                reference_id=reference,
                mode="capacity",
                window="capacity",
                expires_at=expires_at,
                usage={"source": "upload.create"},
            )
            reservations.append((dimension, reference))
        record = repository.create_upload(
            principal.tenant_id,
            upload_id=upload_id,
            filename=payload.filename,
            safe_name=Path(payload.filename).name,
            declared_size_bytes=payload.size_bytes,
            declared_media_type=payload.media_type,
            declared_sha256=payload.sha256,
            expires_at=expires_at,
        )
    except Exception:
        for dimension, reference in reservations:
            try:
                repository.release_quota(
                    principal.tenant_id,
                    dimension=dimension,
                    reference_id=reference,
                )
            except Exception:
                pass
        raise
    _audit(
        request,
        principal,
        action="upload.create",
        resource_type="upload",
        resource_id=upload_id,
        payload={"declared_size_bytes": payload.size_bytes, "filename": payload.filename},
    )
    return {
        **_public_upload(record),
        "content_url": f"/v1/uploads/{upload_id}/content",
        "upload_url": f"/v1/uploads/{upload_id}/content",
        "max_size_bytes": settings.max_upload_bytes,
    }


@router.get("/v1/uploads")
def list_uploads(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    bound: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    records = _repository(request).list_uploads(
        principal.tenant_id,
        status=status_filter,
        bound=bound,
        limit=limit,
        offset=offset,
    )
    return {"items": [_public_upload(item) for item in records], "limit": limit, "offset": offset}


@router.get("/v1/uploads/{upload_id}")
def get_upload(
    upload_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _public_upload(_repository(request).get_upload(principal.tenant_id, upload_id))


@router.put("/v1/uploads/{upload_id}/content")
async def put_upload_content(
    upload_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.UPLOADS_WRITE)),
) -> dict[str, Any]:
    settings = request.app.state.settings
    repository = _repository(request)
    upload = repository.get_upload(principal.tenant_id, upload_id)
    if upload["status"] != "pending":
        raise RepositoryConflict("upload content is already finalized")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{upload_id}-", suffix=".upload")
    os.close(descriptor)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    received = 0
    stored_key: str | None = None
    try:
        with temporary.open("wb") as handle:
            async for chunk in request.stream():
                received += len(chunk)
                if received > upload["declared_size_bytes"] or received > settings.max_upload_bytes:
                    raise AppError("source_invalid", "uploaded content exceeds the declared size", status_code=413)
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if received != upload["declared_size_bytes"]:
            raise AppError("upload_incomplete", "uploaded content size does not match declaration")

        try:
            scan = request.app.state.upload_scanner.scan(
                temporary,
                filename=upload["filename"],
                declared_media_type=upload["declared_media_type"],
            )
        except UploadScannerUnavailable as exc:
            raise AppError("internal_error", "upload scanner is unavailable", status_code=503) from exc

        sha256 = digest.hexdigest()
        namespace = "uploads" if scan.status == "clean" else "quarantine"
        stored_key = f"tenants/{principal.tenant_id}/{namespace}/{upload_id}/{sha256}"
        metadata = request.app.state.object_store.put_file(
            stored_key,
            temporary,
            media_type=scan.detected_media_type,
        )
        record = repository.complete_upload(
            principal.tenant_id,
            upload_id,
            object_key=stored_key,
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            detected_media_type=scan.detected_media_type,
            scan_status=scan.status,
        )
    except Exception:
        if stored_key is not None:
            try:
                current = repository.get_upload(
                    principal.tenant_id,
                    upload_id,
                    include_expired=True,
                )
            except RepositoryNotFound:
                current = None
            if current is None or current.get("object_key") != stored_key:
                request.app.state.object_store.delete(stored_key)
        raise
    finally:
        temporary.unlink(missing_ok=True)

    _audit(
        request,
        principal,
        action="upload.scan",
        resource_type="upload",
        resource_id=upload_id,
        payload={
            "scan_status": scan.status,
            "scanner": scan.scanner,
            "reason": scan.reason,
            "size_bytes": received,
        },
    )
    return _public_upload(record)


@router.delete("/v1/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(
    upload_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.UPLOADS_WRITE)),
) -> Response:
    repository = _repository(request)
    object_key = repository.delete_upload(principal.tenant_id, upload_id)
    if object_key:
        request.app.state.object_store.delete(object_key)
    _release_upload_quota(repository, principal.tenant_id, upload_id)
    _audit(
        request,
        principal,
        action="upload.delete",
        resource_type="upload",
        resource_id=upload_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: CreateJobRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_permission(Permission.JOBS_CREATE)),
) -> dict[str, Any]:
    if payload.input_mode is InputMode.project or payload.seed_project:
        raise AppError(
            "request_invalid",
            "distributed deployments accept only source or structured input",
            status_code=400,
        )
    key = (idempotency_key or payload.client_request_id or "").strip()
    if len(key) < 8:
        raise AppError(
            "request_invalid",
            "Idempotency-Key or client_request_id with at least 8 characters is required",
            status_code=400,
        )
    settings = request.app.state.settings
    repository = _repository(request)
    request_payload = payload.model_dump(mode="json", exclude_none=False)
    request_hash = sha256_json({"tenant_id": principal.tenant_id, "payload": request_payload})
    idempotency_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    existing = repository.find_idempotent_job(
        principal.tenant_id,
        idempotency_hash,
        request_hash=request_hash,
    )
    if existing is not None:
        return {
            "job": existing,
            "job_id": existing["job_id"],
            "created": False,
            "job_url": f"/jobs/{existing['job_id']}",
            "api_url": f"/v1/jobs/{existing['job_id']}",
        }

    manifest = build_job_manifest(
        settings,
        project_name=payload.project_name,
        approval_mode=payload.approval_mode,
        input_mode=payload.input_mode,
        idempotency_key=key,
        target_duration=payload.target_duration,
        target_duration_seconds=(
            payload.target_duration_seconds.model_dump()
            if payload.target_duration_seconds is not None
            else None
        ),
        program=payload.program,
        upload_ids=payload.upload_ids,
        structured_input=payload.structured_input,
        budget_limit_micros=payload.budget_limit_micros,
    )
    manifest.update(
        {
            "status": "queued",
            "display_status": "已排队",
            "stage": "ingest.validate",
            "stage_progress": {
                "ingest.validate": {"stage": "ingest.validate", "status": "queued"}
            },
            "overall_progress": 0.0,
            "can_cancel": True,
        }
    )
    registrations: list[JobInputRegistration] = []
    for upload_id in payload.upload_ids:
        upload = repository.get_upload(principal.tenant_id, upload_id)
        if upload["status"] != "complete" or upload["scan_status"] != "clean":
            raise RepositoryConflict("upload has not passed quarantine scanning")
        registrations.append(
            JobInputRegistration(
                input_id=new_id("inp"),
                kind="upload",
                upload_id=upload_id,
                object_key=upload["object_key"],
                sha256=upload["sha256"],
                size_bytes=upload["size_bytes"],
                media_type=upload["detected_media_type"] or upload["declared_media_type"],
                metadata={"filename": upload["filename"], "upload_id": upload_id},
            )
        )

    structured_key: str | None = None
    if payload.structured_input is not None:
        content = canonical_json(payload.structured_input).encode("utf-8")
        if len(content) > settings.max_upload_bytes:
            raise AppError("source_invalid", "structured input exceeds the configured size limit", status_code=413)
        structured_sha = hashlib.sha256(content).hexdigest()
        structured_input_id = new_id("inp")
        structured_key = (
            f"tenants/{principal.tenant_id}/inputs/{manifest['job_id']}/"
            f"{structured_input_id}/{structured_sha}.json"
        )
        metadata = request.app.state.object_store.put_bytes(
            structured_key,
            content,
            media_type="application/json",
        )
        registrations.append(
            JobInputRegistration(
                input_id=structured_input_id,
                kind="structured",
                object_key=structured_key,
                sha256=metadata.sha256,
                size_bytes=metadata.size_bytes,
                media_type="application/json",
                extraction_status="ready",
            )
        )

    try:
        job, initial_stage, inserted = repository.create_job_bundle(
            principal.tenant_id,
            manifest,
            inputs=registrations,
            request_hash=request_hash,
            actor_id=principal.actor_id,
            request_id=_request_id(request),
            config_snapshot={
                "manifest_version": 2,
                "contract_versions": manifest["contract_versions"],
                "prompt_pins": manifest["prompt_pins"],
                "task_registry": manifest["task_registry"],
            },
            engine_snapshot={"source": "immutable-worker-image"},
        )
    except Exception:
        if structured_key is not None:
            request.app.state.object_store.delete(structured_key)
        raise
    if not inserted and structured_key is not None:
        request.app.state.object_store.delete(structured_key)
    return {
        "job": job,
        "job_id": job["job_id"],
        "initial_stage": initial_stage,
        "created": inserted,
        "job_url": f"/jobs/{job['job_id']}",
        "api_url": f"/v1/jobs/{job['job_id']}",
    }


@router.get("/v1/jobs")
def list_jobs(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    query: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=200),
    needs_action: bool | None = None,
    approval_mode: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    repository = _repository(request)
    if query and q and query != q:
        raise AppError("request_invalid", "query and q filters disagree", status_code=400)
    search_query = query or q
    filters = {
        "status": status_filter,
        "query": search_query,
        "needs_action": needs_action,
        "approval_mode": approval_mode,
        "created_from": created_from,
        "created_to": created_to,
    }
    items = repository.list_jobs(
        principal.tenant_id,
        **filters,
        limit=limit,
        offset=offset,
    )
    total = repository.count_jobs(principal.tenant_id, **filters)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    repository = _repository(request)
    return {
        "job": repository.get_job(principal.tenant_id, job_id),
        "inputs": [
            _public_input(item)
            for item in repository.list_job_inputs(principal.tenant_id, job_id)
        ],
        "artifacts": [
            _public_artifact(item)
            for item in repository.list_job_artifacts(principal.tenant_id, job_id)
        ],
        "stage_runs": repository.list_stage_runs(principal.tenant_id, job_id),
    }


@router.get("/v1/jobs/{job_id}/events")
def job_events(
    job_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    items = _repository(request).list_events(principal.tenant_id, job_id, after=after)
    return {"items": items, "last_sequence": items[-1]["seq"] if items else after}


@router.get("/v1/jobs/{job_id}/events/stream")
def job_event_stream(
    job_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    follow: bool = Query(True),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> StreamingResponse:
    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    repository = _repository(request)
    events = repository.list_events(principal.tenant_id, job_id, after=after)

    async def generate() -> AsyncIterator[str]:
        cursor = after
        pending = events
        idle_ticks = 0
        yield "retry: 2000\n\n"
        while True:
            for event in pending:
                cursor = max(cursor, int(event["seq"]))
                payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event['seq']}\nevent: job-event\ndata: {payload}\n\n"

            if not follow:
                yield f": heartbeat {cursor}\n\n"
                break
            if await request.is_disconnected():
                break

            try:
                job = await asyncio.to_thread(repository.get_job, principal.tenant_id, job_id)
            except RepositoryNotFound:
                break
            if job.get("status") in TERMINAL_JOB_STATUSES:
                yield f": heartbeat {cursor}\n\n"
                break

            await asyncio.sleep(1)
            pending = await asyncio.to_thread(
                repository.list_events,
                principal.tenant_id,
                job_id,
                after=cursor,
            )
            idle_ticks += 1
            if not pending and idle_ticks % 10 == 0:
                yield f": heartbeat {cursor}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/v1/jobs/{job_id}/artifacts")
def list_artifacts(
    job_id: str,
    request: Request,
    current_only: bool = True,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    items = _repository(request).list_job_artifacts(
        principal.tenant_id,
        job_id,
        current_only=current_only,
    )
    return {"items": [_public_artifact(item) for item in items]}


@router.get("/v1/jobs/{job_id}/revisions/{revision_id}")
def get_revision(
    job_id: str,
    revision_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    revision = _repository(request).get_artifact_revision(principal.tenant_id, revision_id)
    if revision["job_id"] != job_id:
        raise RepositoryNotFound("artifact revision not found")
    revision["artifacts"] = [_public_artifact(item) for item in revision["artifacts"]]
    return revision


@router.post("/v1/jobs/{job_id}/artifacts/{logical_name:path}/download")
def create_artifact_download(
    job_id: str,
    logical_name: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    artifact = _repository(request).get_artifact_blob(
        principal.tenant_id,
        job_id,
        logical_name,
    )
    ttl = request.app.state.settings.signed_url_ttl_seconds
    token = request.app.state.object_signer.issue(
        tenant_id=principal.tenant_id,
        job_id=job_id,
        object_key=artifact["object_key"],
        expires_at=int(time.time()) + ttl,
    )
    _audit(
        request,
        principal,
        action="artifact.download.issue",
        resource_type="artifact",
        resource_id=artifact["blob_id"],
        payload={
            "logical_name": artifact["logical_name"],
            "expires_in": ttl,
            "delivery_mode": "authorized_proxy",
        },
    )
    base = str(request.base_url).rstrip("/")
    return {
        "download_url": (
            f"{base}/v1/downloads/{quote(principal.tenant_id, safe='')}/"
            f"{quote(job_id, safe='')}/{quote(token, safe='')}"
        ),
        "expires_in": ttl,
    }


@router.get("/v1/downloads/{tenant_id}/{job_id}/{token}", include_in_schema=False)
def local_artifact_download(tenant_id: str, job_id: str, token: str, request: Request) -> StreamingResponse:
    try:
        payload = request.app.state.object_signer.verify(
            token,
            tenant_id=tenant_id,
            job_id=job_id,
            now_epoch=int(time.time()),
        )
        object_key = str(payload["object_key"])
        _repository(request).get_artifact_blob_by_object_key(tenant_id, job_id, object_key)
        metadata = request.app.state.object_store.head(object_key)
        handle = request.app.state.object_store.open(object_key)
    except (SignedObjectTokenError, RepositoryNotFound, ObjectStoreError) as exc:
        raise AppError("not_found", "download not found") from exc

    def stream() -> Iterator[bytes]:
        try:
            while chunk := handle.read(1024 * 1024):
                yield chunk
        finally:
            handle.close()

    return StreamingResponse(
        stream(),
        media_type=metadata.media_type,
        headers={
            "Content-Length": str(metadata.size_bytes),
            "Content-Disposition": "attachment",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/v1/jobs/{job_id}")
def delete_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    repository = _repository(request)
    result = repository.mark_job_deleted(
        principal.tenant_id,
        job_id,
        recovery_days=request.app.state.settings.deletion_recovery_days,
    )
    _audit(request, principal, action="job.delete", resource_type="job", resource_id=job_id)
    return result


@router.post("/v1/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    payload: CancelJobRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_CANCEL)),
) -> dict[str, Any]:
    result = _repository(request).request_job_cancel(
        principal.tenant_id,
        job_id,
        actor_id=principal.actor_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return {"job": result}


@router.post("/v1/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_job(
    job_id: str,
    payload: RetryJobRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_RETRY)),
) -> dict[str, Any]:
    job, stage_run, created = _repository(request).retry_job(
        principal.tenant_id,
        job_id,
        actor_id=principal.actor_id,
        stage=payload.stage,
        request_id=_request_id(request),
    )
    return {"job": job, "stage_run": stage_run, "created": created}


@router.post("/v1/jobs/{job_id}/budget/decision")
def decide_job_budget(
    job_id: str,
    payload: BudgetDecisionRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.APPROVALS_DECIDE)),
) -> dict[str, Any]:
    if payload.decision == "approved" and payload.resolution is None:
        raise AppError("request_invalid", "approved budget decisions require a resolution")
    if payload.resolution == "raise_limit":
        if principal.role != "admin":
            raise AppError("forbidden", "only an administrator may raise a job budget")
        require_recent_reauthentication(request, principal)
        if payload.new_limit_micros is None:
            raise AppError("request_invalid", "new_limit_micros is required when raising a budget")
    if payload.resolution == "reduce_scope" and not payload.reduced_scope:
        raise AppError("request_invalid", "reduced_scope is required when reducing generation scope")
    return _repository(request).decide_budget(
        principal.tenant_id,
        job_id,
        decision=payload.decision,
        resolution=payload.resolution,
        actor_id=principal.actor_id,
        reason=payload.reason,
        expected_job_version=payload.expected_job_version,
        new_limit_micros=payload.new_limit_micros,
        reduced_scope=payload.reduced_scope,
        request_id=_request_id(request),
    )


@router.post("/v1/jobs/{job_id}/restore")
def restore_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    result = _repository(request).restore_deleted_job(principal.tenant_id, job_id)
    _audit(request, principal, action="job.restore", resource_type="job", resource_id=job_id)
    return result


@router.patch("/v1/jobs/{job_id}/protection")
def update_job_protection(
    job_id: str,
    payload: ProtectionUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.RETENTION_MANAGE)),
) -> dict[str, Any]:
    if payload.legal_hold is not None:
        require_recent_reauthentication(request, principal)
    result = _repository(request).set_job_protection(
        principal.tenant_id,
        job_id,
        pinned=payload.pinned,
        legal_hold=payload.legal_hold,
    )
    _audit(
        request,
        principal,
        action="job.protection.update",
        resource_type="job",
        resource_id=job_id,
        payload=payload.model_dump(exclude_none=True),
    )
    return result


@router.get("/v1/governance")
def get_governance(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.GOVERNANCE_READ)),
) -> dict[str, Any]:
    return _repository(request).get_tenant(principal.tenant_id)


@router.patch("/v1/governance")
def update_governance(
    payload: GovernanceUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.GOVERNANCE_WRITE)),
) -> dict[str, Any]:
    require_recent_reauthentication(request, principal)
    result = _repository(request).update_tenant_governance(
        principal.tenant_id,
        quotas=payload.quotas,
        retention=payload.retention,
        policy=payload.policy,
    )
    _audit(
        request,
        principal,
        action="governance.update",
        resource_type="tenant",
        resource_id=principal.tenant_id,
        payload={"fields": sorted(payload.model_dump(exclude_none=True))},
    )
    return result


@router.get("/v1/members")
def list_members(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.GOVERNANCE_READ)),
) -> dict[str, Any]:
    return {"items": _repository(request).list_memberships(principal.tenant_id)}


@router.put("/v1/members/{user_id}")
def update_member(
    user_id: str,
    payload: MembershipUpdate,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.MEMBERS_MANAGE)),
) -> dict[str, Any]:
    require_recent_reauthentication(request, principal)
    repository = _repository(request)
    repository.ensure_user(
        user_id,
        oidc_subject=payload.subject,
        email=payload.email,
        display_name=payload.display_name,
    )
    repository.set_membership(
        principal.tenant_id,
        user_id,
        payload.role,
        disabled=payload.disabled,
    )
    _audit(
        request,
        principal,
        action="membership.update",
        resource_type="membership",
        resource_id=user_id,
        payload={"role": payload.role, "disabled": payload.disabled},
    )
    return repository.membership_for_subject(principal.tenant_id, payload.subject) or {}


@router.get("/v1/costs/summary")
def cost_summary(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.COST_READ)),
) -> dict[str, Any]:
    return _repository(request).tenant_cost_summary(principal.tenant_id)


@router.get("/v1/jobs/{job_id}/costs")
def job_costs(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.COST_READ)),
) -> dict[str, Any]:
    return {"items": _repository(request).cost_ledger(principal.tenant_id, job_id)}


@router.get("/v1/quotas")
def quotas(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.QUOTA_READ)),
) -> dict[str, Any]:
    repository = _repository(request)
    dimensions = (
        ("active_jobs", "capacity", "capacity"),
        ("upload_bytes", "capacity", "capacity"),
        ("upload_files", "capacity", "capacity"),
    )
    return {
        "items": [
            repository.quota_summary(
                principal.tenant_id,
                dimension=dimension,
                mode=mode,
                window=window,
            )
            for dimension, mode, window in dimensions
        ]
    }


@router.get("/v1/jobs/{job_id}/quotas")
def job_quotas(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.QUOTA_READ)),
) -> dict[str, Any]:
    repository = _repository(request)
    repository.get_job(principal.tenant_id, job_id)
    return {"items": repository.quota_ledger(principal.tenant_id, job_id=job_id)}


@router.get("/v1/audit")
def audit_log(
    request: Request,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    job_id: str | None = None,
    actor_id: str | None = None,
    result: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    if resource_id and job_id and resource_id != job_id:
        raise AppError("request_invalid", "resource_id and job_id filters disagree", status_code=400)
    items = _repository(request).list_audit(
        principal.tenant_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id or job_id,
        actor_id=actor_id,
        result=result,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )
    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "has_more": len(items) == limit,
    }


@router.get("/v1/operations/snapshot")
def operations_snapshot(
    request: Request,
    principal: Principal = Depends(require_permission(Permission.WORKER_EXECUTE)),
) -> dict[str, Any]:
    snapshot = _repository(request).operations_snapshot(principal.tenant_id)
    snapshot.update(
        {
            "deployment_mode": "distributed",
            "object_store": request.app.state.settings.object_store_backend,
            "model_routes": _route_readiness(request.app.state.settings),
        }
    )
    return snapshot


@router.get("/v1/retention/jobs")
def retention_jobs(
    request: Request,
    state: Literal["active", "deleted", "all"] = "deleted",
    query: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission(Permission.RETENTION_MANAGE)),
) -> dict[str, Any]:
    items, total = _repository(request).list_lifecycle_jobs(
        principal.tenant_id,
        state=state,
        query=query,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/v1/retention/run")
def run_retention(
    payload: RetentionRunRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.RETENTION_MANAGE)),
) -> dict[str, Any]:
    require_recent_reauthentication(request, principal)
    settings = request.app.state.settings
    tenant = _repository(request).get_tenant(principal.tenant_id)
    retention = tenant.get("retention") if isinstance(tenant.get("retention"), dict) else {}
    now = payload.now or datetime.now(timezone.utc)
    result = _repository(request).apply_retention(
        principal.tenant_id,
        now=now,
        succeeded_days=_retention_days(
            retention.get("succeeded_days"), settings.succeeded_retention_days
        ),
        failed_days=_retention_days(
            retention.get("failed_days"), settings.failed_retention_days
        ),
        recovery_days=_retention_days(
            retention.get("recovery_days"), settings.deletion_recovery_days
        ),
    )
    _audit(
        request,
        principal,
        action="retention.run",
        resource_type="tenant",
        resource_id=principal.tenant_id,
        payload={"hidden_count": len(result["hidden"]), "purge_ready_count": len(result["purge_ready"])},
    )
    return result


@router.post("/v1/retention/jobs/{job_id}/purge")
def permanently_delete_job(
    job_id: str,
    payload: PermanentDeleteRequest,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.RETENTION_MANAGE)),
) -> dict[str, Any]:
    require_recent_reauthentication(request, principal)
    expected_confirmation = f"永久删除 {job_id}"
    if payload.confirmation != expected_confirmation:
        raise AppError(
            "request_invalid",
            f"confirmation must exactly match: {expected_confirmation}",
            status_code=422,
        )

    repository = _repository(request)
    repository.get_job(principal.tenant_id, job_id, include_deleted=True)
    object_keys = repository.purge_job_objects_metadata(
        principal.tenant_id,
        job_id,
        now=datetime.now(timezone.utc),
    )
    deleted_count = 0
    failed_count = 0
    for object_key in object_keys:
        try:
            request.app.state.object_store.delete(object_key)
            deleted_count += 1
        except Exception:  # noqa: BLE001 - orphan maintenance retries object cleanup
            failed_count += 1

    cleanup_status = "purged" if failed_count == 0 else "purged_with_cleanup_errors"
    _audit(
        request,
        principal,
        action="job.purge",
        resource_type="job",
        resource_id=job_id,
        payload={
            "cleanup_status": cleanup_status,
            "object_count": len(object_keys),
            "deleted_object_count": deleted_count,
            "failed_object_count": failed_count,
        },
    )
    return {
        "job_id": job_id,
        "status": cleanup_status,
        "purged": True,
        "object_count": len(object_keys),
        "deleted_object_count": deleted_count,
        "failed_object_count": failed_count,
    }
