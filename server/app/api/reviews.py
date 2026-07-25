from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from server.app.api.jobs import public_manifest
from server.app.models.review import (
    ApprovalRequest,
    EditorialModelRevisionRequest,
    EditorialRevisionRequest,
    RejectionRequest,
    RestoreRevisionRequest,
    VisualModelRevisionRequest,
    VisualRevisionRequest,
)
from server.app.services.queue import JobQueue
from server.app.services.revisions import RevisionService
from server.app.services.storage import StorageError


router = APIRouter()


def get_revisions(request: Request) -> RevisionService:
    return request.app.state.revisions


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def set_review_etag(response: Response, review: dict[str, Any]) -> dict[str, Any]:
    response.headers["ETag"] = review["etag"]
    response.headers["Cache-Control"] = "no-store"
    return review


def storage_not_found(exc: StorageError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/v1/jobs/{job_id}/reviews/editorial")
def get_editorial_review(
    job_id: str,
    response: Response,
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        return set_review_etag(response, revisions.current_review(job_id, "editorial"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/editorial/revisions")
def create_editorial_revision(
    job_id: str,
    payload: EditorialRevisionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.create_editorial(
            job_id,
            title=payload.title,
            narration=payload.narration,
            change_summary=payload.change_summary,
            actor=payload.actor,
            base_revision=payload.base_revision,
            if_match=if_match,
        )
        return set_review_etag(response, revisions.current_review(job_id, "editorial"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/editorial/model-revisions")
def create_editorial_model_revision(
    job_id: str,
    payload: EditorialModelRevisionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.create_editorial_model_revision(
            job_id,
            base_revision=payload.base_revision,
            if_match=if_match,
            feedback=payload.feedback,
            issues=payload.issues,
            change_summary=payload.change_summary,
            actor=payload.actor,
        )
        return set_review_etag(response, revisions.current_review(job_id, "editorial"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/editorial/approve")
def approve_editorial(
    job_id: str,
    payload: ApprovalRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    try:
        manifest = revisions.approve(
            job_id,
            "editorial",
            revision_id=payload.revision,
            base_revision=payload.base_revision,
            if_match=if_match,
            has_unsaved_draft=payload.has_unsaved_draft,
            actor=payload.actor,
            reason=payload.reason,
        )
        if manifest.get("status") == "queued":
            queue.enqueue(job_id)
        review = revisions.current_review(job_id, "editorial")
        set_review_etag(response, review)
        return {**review, "job": public_manifest(manifest, queue)}
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/editorial/reject")
def reject_editorial(
    job_id: str,
    payload: RejectionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.reject(
            job_id,
            "editorial",
            revision_id=payload.revision,
            base_revision=payload.base_revision,
            if_match=if_match,
            actor=payload.actor,
            reason=payload.reason,
        )
        return set_review_etag(response, revisions.current_review(job_id, "editorial"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.get("/v1/jobs/{job_id}/reviews/visual-plan")
def get_visual_review(
    job_id: str,
    response: Response,
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        return set_review_etag(response, revisions.current_review(job_id, "visual-plan"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/revisions")
def create_visual_revision(
    job_id: str,
    payload: VisualRevisionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.create_visual_plan(
            job_id,
            plan=payload.plan,
            rich_storyboard=payload.rich_storyboard,
            image_prompts=payload.image_prompts,
            readiness=payload.readiness,
            change_summary=payload.change_summary,
            actor=payload.actor,
            base_revision=payload.base_revision,
            if_match=if_match,
        )
        return set_review_etag(response, revisions.current_review(job_id, "visual-plan"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/model-revisions")
def create_visual_model_revision(
    job_id: str,
    payload: VisualModelRevisionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.create_visual_model_revision(
            job_id,
            base_revision=payload.base_revision,
            if_match=if_match,
            feedback=payload.feedback,
            issues=payload.issues,
            scene_ids=payload.scene_ids,
            change_summary=payload.change_summary,
            actor=payload.actor,
        )
        return set_review_etag(response, revisions.current_review(job_id, "visual-plan"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/approve")
def approve_visual_plan(
    job_id: str,
    payload: ApprovalRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
    queue: JobQueue = Depends(get_queue),
) -> dict[str, Any]:
    try:
        manifest = revisions.approve(
            job_id,
            "visual-plan",
            revision_id=payload.revision,
            base_revision=payload.base_revision,
            if_match=if_match,
            has_unsaved_draft=payload.has_unsaved_draft,
            actor=payload.actor,
            reason=payload.reason,
        )
        if manifest.get("status") == "queued":
            queue.enqueue(job_id)
        review = revisions.current_review(job_id, "visual-plan")
        set_review_etag(response, review)
        return {**review, "job": public_manifest(manifest, queue)}
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/reject")
def reject_visual_plan(
    job_id: str,
    payload: RejectionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.reject(
            job_id,
            "visual-plan",
            revision_id=payload.revision,
            base_revision=payload.base_revision,
            if_match=if_match,
            actor=payload.actor,
            reason=payload.reason,
        )
        return set_review_etag(response, revisions.current_review(job_id, "visual-plan"))
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.get("/v1/jobs/{job_id}/revisions/{domain}/diff")
def diff_revisions(
    job_id: str,
    domain: str,
    from_revision: str,
    to_revision: str,
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        return revisions.diff(job_id, domain, from_revision, to_revision)
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.get("/v1/jobs/{job_id}/revisions/{domain}")
def list_revisions(
    job_id: str,
    domain: str,
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        return {"domain": domain, "revisions": revisions.list_revisions(job_id, domain)}
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.get("/v1/jobs/{job_id}/revisions/{domain}/{revision_id}")
def get_revision(
    job_id: str,
    domain: str,
    revision_id: str,
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        return revisions.get_revision(job_id, domain, revision_id)
    except StorageError as exc:
        raise storage_not_found(exc) from exc


@router.post("/v1/jobs/{job_id}/revisions/{domain}/{revision_id}/restore")
def restore_revision(
    job_id: str,
    domain: str,
    revision_id: str,
    payload: RestoreRevisionRequest,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    revisions: RevisionService = Depends(get_revisions),
) -> dict[str, Any]:
    try:
        revisions.restore(
            job_id,
            domain,
            revision_id,
            base_revision=payload.base_revision,
            if_match=if_match,
            change_summary=payload.change_summary,
            actor=payload.actor,
        )
        review = revisions.current_review(job_id, domain)
        return set_review_etag(response, review)
    except StorageError as exc:
        raise storage_not_found(exc) from exc
