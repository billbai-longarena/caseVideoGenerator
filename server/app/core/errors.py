from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorDescriptor:
    retryable: bool
    status_code: int


ERROR_CATALOG: dict[str, ErrorDescriptor] = {
    "source_invalid": ErrorDescriptor(False, 400),
    "source_extract_failed": ErrorDescriptor(True, 422),
    "source_ocr_required": ErrorDescriptor(False, 422),
    "upload_incomplete": ErrorDescriptor(False, 409),
    "upload_expired": ErrorDescriptor(False, 410),
    "upload_bound": ErrorDescriptor(False, 409),
    "idempotency_conflict": ErrorDescriptor(False, 409),
    "model_task_unregistered": ErrorDescriptor(False, 500),
    "model_route_missing": ErrorDescriptor(False, 503),
    "model_route_unavailable": ErrorDescriptor(True, 503),
    "model_provider_unsupported": ErrorDescriptor(False, 500),
    "model_provider_error": ErrorDescriptor(True, 502),
    "model_output_invalid": ErrorDescriptor(True, 422),
    "contract_invalid": ErrorDescriptor(False, 500),
    "semantic_review_blocked": ErrorDescriptor(False, 422),
    "revision_conflict": ErrorDescriptor(False, 409),
    "approval_required": ErrorDescriptor(False, 409),
    "readiness_blocked": ErrorDescriptor(False, 422),
    "budget_exceeded": ErrorDescriptor(False, 402),
    "stage_timeout": ErrorDescriptor(True, 504),
    "artifact_corrupt": ErrorDescriptor(False, 422),
    "render_workspace_busy": ErrorDescriptor(True, 409),
    "canceled": ErrorDescriptor(False, 409),
    "request_invalid": ErrorDescriptor(False, 422),
    "not_found": ErrorDescriptor(False, 404),
    "unauthorized": ErrorDescriptor(False, 401),
    "forbidden": ErrorDescriptor(False, 403),
    "quota_exceeded": ErrorDescriptor(False, 429),
    "rate_limited": ErrorDescriptor(True, 429),
    "internal_error": ErrorDescriptor(False, 500),
}


class AppError(RuntimeError):
    """Stable application error safe to expose through the public API."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        status_code: int | None = None,
        stage: str | None = None,
        action_url: str | None = None,
        error_id: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        public_details: dict[str, Any] | None = None,
    ) -> None:
        descriptor = ERROR_CATALOG.get(code, ERROR_CATALOG["internal_error"])
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = descriptor.retryable if retryable is None else retryable
        self.status_code = descriptor.status_code if status_code is None else status_code
        self.stage = stage
        self.action_url = action_url
        self.error_id = error_id or f"err_{uuid.uuid4().hex[:16]}"
        self.diagnostics = diagnostics or {}
        self.public_details = public_details or {}

    def public_payload(self, request_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": request_id,
            "error_id": self.error_id,
            "code": self.code,
            "message": self.message,
            "detail": self.message,
            "retryable": self.retryable,
            "stage": self.stage,
        }
        if self.action_url:
            payload["action_url"] = self.action_url
        if self.public_details:
            payload.update(self.public_details)
        return payload


def request_id_from_scope(scope: Any) -> str:
    state = getattr(scope, "state", None)
    request_id = getattr(state, "request_id", None) if state is not None else None
    return request_id or f"req_{uuid.uuid4().hex[:16]}"
