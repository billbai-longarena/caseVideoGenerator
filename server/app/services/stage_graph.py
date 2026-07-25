from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDefinition:
    name: str
    display: str
    handler: str
    queue: str
    model_task: str | None = None
    approval_gate: str | None = None


PIPELINE_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition("ingest.validate", "校验输入材料", "_stage_ingest_validate", "planning"),
    StageDefinition("source.extract", "提取并规范化来源材料", "_stage_source_extract", "planning"),
    StageDefinition("case.model", "构建案例事实模型", "_stage_case_model", "planning", "case.model"),
    StageDefinition(
        "editorial.compose",
        "生成标题与旁白",
        "_stage_editorial_compose",
        "planning",
        "narration.compose",
    ),
    StageDefinition("editorial.lint", "执行文稿确定性检查", "_stage_editorial_lint", "planning"),
    StageDefinition(
        "editorial.review",
        "执行独立文稿审阅",
        "_stage_editorial_review",
        "planning",
        "editorial.review",
    ),
    StageDefinition(
        "editorial.rewrite",
        "修订标题与旁白",
        "_stage_editorial_rewrite",
        "planning",
        "narration.rewrite",
    ),
    StageDefinition(
        "editorial.approval",
        "等待标题与旁白审批",
        "_stage_editorial_approval",
        "planning",
        approval_gate="editorial",
    ),
    StageDefinition("tts.generate", "生成 Azure 旁白与时间轴", "_stage_tts_generate", "media"),
    StageDefinition(
        "visual.plan",
        "生成 Remotion 视觉计划",
        "_stage_visual_plan",
        "planning",
        "remotion.plan",
    ),
    StageDefinition("visual.build", "构建富分镜", "_stage_visual_build", "planning"),
    StageDefinition(
        "visual.repair",
        "修复视觉计划",
        "_stage_visual_repair",
        "planning",
        "remotion.repair",
    ),
    StageDefinition(
        "visual.contract-approval",
        "等待视觉合同审批",
        "_stage_visual_contract_approval",
        "planning",
        approval_gate="visual_contract",
    ),
    StageDefinition(
        "assets.generate",
        "生成场景视觉资产",
        "_stage_assets_generate",
        "media",
        "image_prompt.refine",
    ),
    StageDefinition("visual.preview", "渲染导演意图代表帧", "_stage_visual_preview", "render"),
    StageDefinition(
        "visual.intent-review",
        "对照导演意图审片",
        "_stage_visual_intent_review",
        "qa",
        "remotion.frame-review",
    ),
    StageDefinition(
        "visual.approval",
        "等待成片视觉审批",
        "_stage_visual_approval",
        "planning",
        approval_gate="visual",
    ),
    StageDefinition("render.prepare", "执行渲染前检查", "_stage_render_prepare", "render"),
    StageDefinition("render.execute", "执行 Remotion 渲染", "_stage_render_execute", "render"),
    StageDefinition("qa.execute", "执行音视频交付 QA", "_stage_qa_execute", "qa"),
    StageDefinition(
        "delivery.finalize",
        "生成交付索引与摘要",
        "_stage_delivery_finalize",
        "qa",
        "delivery.summarize",
    ),
)

STAGE_BY_NAME = {stage.name: stage for stage in PIPELINE_STAGES}
STAGE_INDEX = {stage.name: index for index, stage in enumerate(PIPELINE_STAGES)}
STAGE_QUEUES = {stage.name: stage.queue for stage in PIPELINE_STAGES}


def stage_definition(stage_name: str) -> StageDefinition:
    try:
        return STAGE_BY_NAME[stage_name]
    except KeyError as exc:
        raise ValueError(f"unknown pipeline stage: {stage_name}") from exc


def next_stage_name(stage_name: str) -> str | None:
    try:
        index = STAGE_INDEX[stage_name]
    except KeyError as exc:
        raise ValueError(f"unknown pipeline stage: {stage_name}") from exc
    if index + 1 >= len(PIPELINE_STAGES):
        return None
    return PIPELINE_STAGES[index + 1].name


def pipeline_catalog() -> list[dict[str, str | int | None]]:
    return [
        {
            "index": index,
            "name": stage.name,
            "display": stage.display,
            "model_task": stage.model_task,
            "queue": stage.queue,
            "approval_gate": stage.approval_gate,
        }
        for index, stage in enumerate(PIPELINE_STAGES, start=1)
    ]
