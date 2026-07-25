from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response, status

from server.app.models.review import (
    ApprovalRequest,
    EditorialModelRevisionRequest,
    EditorialRevisionRequest,
    RejectionRequest,
    RestoreRevisionRequest,
    VisualModelRevisionRequest,
    VisualRevisionRequest,
)
from server.app.security.auth import Permission, Principal, require_permission
from server.app.services.distributed_revisions import DistributedRevisionService


router = APIRouter()
RevisionDomain = Literal["case-model", "editorial", "visual-plan"]


def _service(request: Request) -> DistributedRevisionService:
    return request.app.state.distributed_revisions


def _request_id(request: Request) -> str | None:
    return str(getattr(request.state, "request_id", "")) or None


def _with_etag(response: Response, review: dict[str, Any]) -> dict[str, Any]:
    response.headers["ETag"] = str(review["etag"])
    response.headers["Cache-Control"] = "no-store"
    return review


def _current_review(
    request: Request,
    response: Response,
    principal: Principal,
    domain: str,
) -> dict[str, Any]:
    review = _service(request).current_review(principal.tenant_id, request.path_params["job_id"], domain)
    return _with_etag(response, review)


@router.get("/v1/jobs/{job_id}/reviews/editorial")
def get_editorial_review(
    job_id: str,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    del job_id
    return _current_review(request, response, principal, "editorial")


@router.post("/v1/jobs/{job_id}/reviews/editorial/revisions")
def create_editorial_revision(
    job_id: str,
    payload: EditorialRevisionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    service = _service(request)
    service.create_editorial(
        principal.tenant_id,
        job_id,
        title=payload.title,
        narration=payload.narration,
        change_summary=payload.change_summary,
        actor=principal.actor_id,
        base_revision=payload.base_revision,
        if_match=if_match,
        request_id=_request_id(request),
    )
    return _with_etag(response, service.current_review(principal.tenant_id, job_id, "editorial"))


@router.post(
    "/v1/jobs/{job_id}/reviews/editorial/model-revisions",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_editorial_model_revision(
    job_id: str,
    payload: EditorialModelRevisionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    service = _service(request)
    queued = service.request_model_revision(
        principal.tenant_id,
        job_id,
        "editorial",
        base_revision=payload.base_revision,
        if_match=if_match,
        feedback=payload.feedback,
        issues=payload.issues,
        change_summary=payload.change_summary,
        actor=principal.actor_id,
        request_id=_request_id(request),
    )
    review = service.current_review(principal.tenant_id, job_id, "editorial")
    return {**_with_etag(response, review), **queued}


@router.post("/v1/jobs/{job_id}/reviews/editorial/approve")
def approve_editorial(
    job_id: str,
    payload: ApprovalRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.APPROVALS_DECIDE)),
) -> dict[str, Any]:
    service = _service(request)
    decision = service.approve(
        principal.tenant_id,
        job_id,
        "editorial",
        revision_id=payload.revision,
        base_revision=payload.base_revision,
        if_match=if_match,
        has_unsaved_draft=payload.has_unsaved_draft,
        actor=principal.actor_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    review = service.current_review(principal.tenant_id, job_id, "editorial")
    return {**_with_etag(response, review), **decision}


@router.post("/v1/jobs/{job_id}/reviews/editorial/reject")
def reject_editorial(
    job_id: str,
    payload: RejectionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.APPROVALS_DECIDE)),
) -> dict[str, Any]:
    service = _service(request)
    decision = service.reject(
        principal.tenant_id,
        job_id,
        "editorial",
        revision_id=payload.revision,
        base_revision=payload.base_revision,
        if_match=if_match,
        actor=principal.actor_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    review = service.current_review(principal.tenant_id, job_id, "editorial")
    return {**_with_etag(response, review), **decision}


@router.get("/v1/jobs/{job_id}/reviews/visual-plan")
def get_visual_review(
    job_id: str,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    del job_id
    return _current_review(request, response, principal, "visual-plan")


@router.get("/v1/jobs/{job_id}/model-revision-requests/{request_id}")
def get_model_revision_request(
    job_id: str,
    request_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _service(request).get_model_revision_request(principal.tenant_id, job_id, request_id)


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/revisions")
def create_visual_revision(
    job_id: str,
    payload: VisualRevisionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    service = _service(request)
    service.create_visual_plan(
        principal.tenant_id,
        job_id,
        plan=payload.plan,
        rich_storyboard=payload.rich_storyboard,
        image_prompts=payload.image_prompts,
        readiness=payload.readiness,
        change_summary=payload.change_summary,
        actor=principal.actor_id,
        base_revision=payload.base_revision,
        if_match=if_match,
        request_id=_request_id(request),
    )
    return _with_etag(response, service.current_review(principal.tenant_id, job_id, "visual-plan"))


@router.post(
    "/v1/jobs/{job_id}/reviews/visual-plan/model-revisions",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_visual_model_revision(
    job_id: str,
    payload: VisualModelRevisionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    service = _service(request)
    queued = service.request_model_revision(
        principal.tenant_id,
        job_id,
        "visual-plan",
        base_revision=payload.base_revision,
        if_match=if_match,
        feedback=payload.feedback,
        issues=payload.issues,
        scene_ids=payload.scene_ids,
        change_summary=payload.change_summary,
        actor=principal.actor_id,
        request_id=_request_id(request),
    )
    review = service.current_review(principal.tenant_id, job_id, "visual-plan")
    return {**_with_etag(response, review), **queued}


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/approve")
def approve_visual_plan(
    job_id: str,
    payload: ApprovalRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.APPROVALS_DECIDE)),
) -> dict[str, Any]:
    service = _service(request)
    decision = service.approve(
        principal.tenant_id,
        job_id,
        "visual-plan",
        revision_id=payload.revision,
        base_revision=payload.base_revision,
        if_match=if_match,
        has_unsaved_draft=payload.has_unsaved_draft,
        actor=principal.actor_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    review = service.current_review(principal.tenant_id, job_id, "visual-plan")
    return {**_with_etag(response, review), **decision}


@router.post("/v1/jobs/{job_id}/reviews/visual-plan/reject")
def reject_visual_plan(
    job_id: str,
    payload: RejectionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.APPROVALS_DECIDE)),
) -> dict[str, Any]:
    service = _service(request)
    decision = service.reject(
        principal.tenant_id,
        job_id,
        "visual-plan",
        revision_id=payload.revision,
        base_revision=payload.base_revision,
        if_match=if_match,
        actor=principal.actor_id,
        reason=payload.reason,
        request_id=_request_id(request),
    )
    review = service.current_review(principal.tenant_id, job_id, "visual-plan")
    return {**_with_etag(response, review), **decision}


def _list_revisions(
    job_id: str,
    domain: RevisionDomain,
    request: Request,
    principal: Principal,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "revisions": _service(request).list_revisions(principal.tenant_id, job_id, domain),
    }


@router.get("/v1/jobs/{job_id}/revisions/case-model")
def list_case_model_revisions(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _list_revisions(job_id, "case-model", request, principal)


@router.get("/v1/jobs/{job_id}/revisions/editorial")
def list_editorial_revisions(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _list_revisions(job_id, "editorial", request, principal)


@router.get("/v1/jobs/{job_id}/revisions/visual-plan")
def list_visual_revisions(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _list_revisions(job_id, "visual-plan", request, principal)


@router.get("/v1/jobs/{job_id}/revisions/{domain}/diff")
def diff_revisions(
    job_id: str,
    domain: RevisionDomain,
    from_revision: str,
    to_revision: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _service(request).diff(
        principal.tenant_id,
        job_id,
        domain,
        from_revision,
        to_revision,
    )


@router.get("/v1/jobs/{job_id}/revisions/{domain}/{revision_id}")
def get_domain_revision(
    job_id: str,
    domain: RevisionDomain,
    revision_id: str,
    request: Request,
    principal: Principal = Depends(require_permission(Permission.JOBS_READ)),
) -> dict[str, Any]:
    return _service(request).get_revision(principal.tenant_id, job_id, domain, revision_id)


@router.post("/v1/jobs/{job_id}/revisions/{domain}/{revision_id}/restore")
def restore_revision(
    job_id: str,
    domain: RevisionDomain,
    revision_id: str,
    payload: RestoreRevisionRequest,
    request: Request,
    response: Response,
    if_match: str = Header(..., alias="If-Match"),
    principal: Principal = Depends(require_permission(Permission.JOBS_EDIT)),
) -> dict[str, Any]:
    service = _service(request)
    service.restore(
        principal.tenant_id,
        job_id,
        domain,
        revision_id,
        base_revision=payload.base_revision,
        if_match=if_match,
        change_summary=payload.change_summary,
        actor=principal.actor_id,
        request_id=_request_id(request),
    )
    return _with_etag(response, service.current_review(principal.tenant_id, job_id, domain))
