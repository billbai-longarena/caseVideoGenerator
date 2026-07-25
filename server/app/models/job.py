from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ApprovalMode(str, Enum):
    editorial = "editorial"
    auto = "auto"
    full = "full"


class InputMode(str, Enum):
    source = "source"
    structured = "structured"
    project = "project"


class DurationRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(240, ge=60, le=1_800)
    max: int = Field(420, ge=60, le=1_800)

    @model_validator(mode="after")
    def validate_range(self) -> "DurationRange":
        if self.min > self.max:
            raise ValueError("target duration min must not exceed max")
        return self


class JobStatus(str, Enum):
    created = "created"
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    succeeded = "succeeded"
    failed = "failed"
    canceling = "canceling"
    canceled = "canceled"


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(..., min_length=1, max_length=120)
    input_mode: InputMode = InputMode.project
    approval_mode: ApprovalMode = ApprovalMode.editorial
    target_duration: Optional[str] = Field(None, max_length=80)
    target_duration_seconds: Optional[DurationRange] = None
    program: str = Field("销售不复杂", min_length=1, max_length=80)
    client_request_id: Optional[str] = Field(None, min_length=8, max_length=160)
    upload_ids: list[str] = Field(default_factory=list, max_length=25)
    structured_input: Optional[dict[str, Any]] = None
    budget_limit_micros: Optional[int] = Field(None, ge=0)
    seed_project: Optional[str] = Field(
        None,
        description="Optional project directory name under CASE_VIDEO_SEED_PROJECTS_ROOT.",
    )

    @field_validator("project_name")
    @classmethod
    def project_name_must_not_be_path(cls, value: str) -> str:
        if "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("project_name must be a display name, not a path")
        return value.strip()

    @field_validator("seed_project")
    @classmethod
    def seed_project_must_be_relative(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("seed_project must be a relative directory under the seed root")
        return value.strip("/")

    @field_validator("upload_ids")
    @classmethod
    def upload_ids_are_safe_and_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("upload_ids must be unique")
        for upload_id in value:
            if not upload_id.startswith("upl_") or not upload_id.replace("_", "").isalnum():
                raise ValueError("upload_ids contain an invalid identifier")
        return value

    @model_validator(mode="after")
    def validate_input_contract(self) -> "CreateJobRequest":
        if self.input_mode is InputMode.source:
            if not self.upload_ids and self.structured_input is None:
                raise ValueError("source mode requires upload_ids or structured_input")
            if self.seed_project:
                raise ValueError("source mode cannot use seed_project")
        elif self.input_mode is InputMode.structured:
            if self.structured_input is None:
                raise ValueError("structured mode requires structured_input")
            if self.upload_ids or self.seed_project:
                raise ValueError("structured mode cannot use upload_ids or seed_project")
        elif self.upload_ids or self.structured_input is not None:
            raise ValueError("project mode cannot use upload_ids or structured_input")
        return self


class CreateUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., ge=1)
    media_type: Optional[str] = Field(None, max_length=160)
    sha256: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("filename")
    @classmethod
    def filename_must_be_display_only(cls, value: str) -> str:
        if "\x00" in value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("filename must not contain a path")
        return value.strip()


class UploadRecord(BaseModel):
    upload_id: str
    filename: str
    safe_name: str
    declared_size_bytes: int
    size_bytes: Optional[int] = None
    declared_media_type: Optional[str] = None
    detected_media_type: Optional[str] = None
    sha256: Optional[str] = None
    status: str
    upload_url: Optional[str] = None
    max_size_bytes: int
    created_at: str
    expires_at: str
    bound_job_id: Optional[str] = None


class StageProgress(BaseModel):
    stage: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    input_hash: Optional[str] = None
    command: list[str] = Field(default_factory=list)
    returncode: Optional[int] = None
    error_code: Optional[str] = None


class JobSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    job_id: str
    job_url: str
    project_name: str
    manifest_version: int = 2
    input_mode: str = "project"
    approval_mode: str = "editorial"
    status: JobStatus
    display_status: str
    stage: str
    stage_progress: dict[str, Any] = Field(default_factory=dict)
    overall_progress: float = 0.0
    queue_position: Optional[int] = None
    needs_action: bool = False
    next_action: Optional[str] = None
    can_approve: bool = False
    can_retry: bool = False
    can_cancel: bool = False
    created_at: str
    updated_at: str
    last_heartbeat_at: Optional[str] = None
    current_revisions: dict[str, Optional[str]] = Field(default_factory=dict)
    approved_revisions: dict[str, Optional[str]] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    invalidations: list[dict[str, Any]] = Field(default_factory=list)
    model_routes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    pipeline_stages: list[dict[str, Any]] = Field(default_factory=list)
    stage_runs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error: Optional[dict[str, Any]] = None
    dry_run: bool = False


class ArtifactInfo(BaseModel):
    name: str
    size: int
    modified_at: str
    kind: str
    current: bool = True
    formal_delivery: bool = False


class EventRecord(BaseModel):
    seq: int
    timestamp: str
    type: str
    stage: Optional[str] = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
