from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EditorialRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=120)
    narration: str = Field(..., min_length=1)
    change_summary: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field("user", min_length=1, max_length=160)


class EditorialModelRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str = Field(..., min_length=1, max_length=80)
    feedback: str = Field(..., min_length=1, max_length=4000)
    issues: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    change_summary: str = Field("根据人工反馈进行模型修订", min_length=1, max_length=1000)
    actor: str = Field("user", min_length=1, max_length=160)


class VisualRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str = Field(..., min_length=1, max_length=80)
    plan: dict[str, Any]
    rich_storyboard: dict[str, Any] | None = None
    image_prompts: dict[str, Any] | None = None
    readiness: dict[str, Any] | None = None
    change_summary: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field("user", min_length=1, max_length=160)


class VisualModelRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str = Field(..., min_length=1, max_length=80)
    feedback: str = Field(..., min_length=1, max_length=4000)
    issues: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    scene_ids: list[str] = Field(default_factory=list, max_length=100)
    change_summary: str = Field("根据人工反馈修订视觉计划", min_length=1, max_length=1000)
    actor: str = Field("user", min_length=1, max_length=160)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(..., min_length=1, max_length=80)
    base_revision: str = Field(..., min_length=1, max_length=80)
    has_unsaved_draft: bool = False
    reason: str | None = Field(None, max_length=2000)
    actor: str = Field("user", min_length=1, max_length=160)

    @model_validator(mode="after")
    def revision_is_base_revision(self) -> "ApprovalRequest":
        if self.revision != self.base_revision:
            raise ValueError("revision and base_revision must identify the same displayed revision")
        return self


class RejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(..., min_length=1, max_length=80)
    base_revision: str = Field(..., min_length=1, max_length=80)
    reason: str = Field(..., min_length=1, max_length=2000)
    actor: str = Field("user", min_length=1, max_length=160)

    @model_validator(mode="after")
    def revision_is_base_revision(self) -> "RejectionRequest":
        if self.revision != self.base_revision:
            raise ValueError("revision and base_revision must identify the same displayed revision")
        return self


class RestoreRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: str = Field(..., min_length=1, max_length=80)
    change_summary: str = Field("从历史版本恢复为新版本", min_length=1, max_length=1000)
    actor: str = Field("user", min_length=1, max_length=160)
