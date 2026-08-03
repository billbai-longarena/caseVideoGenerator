from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from server.app.core.config import ModelRoute, Settings
from server.app.core.errors import AppError
from server.app.services.contracts import ContractRegistry


SemanticValidator = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    route_family: str
    prompt_version: str
    input_contract: tuple[str, str]
    output_contract: tuple[str, str]
    timeout_seconds: int = 90
    max_output_bytes: int = 512_000
    max_structure_repairs: int = 2
    max_semantic_revisions: int = 0
    budget_category: str = "text_model"
    allow_source_excerpt: bool = False
    allow_media: bool = False
    require_media: bool = False
    user_visible_text: bool = False
    invalidates_paid_stages: bool = False
    semantic_validator: str = "none"


TASK_SPECS: tuple[TaskSpec, ...] = (
    TaskSpec("source.classify", "general", "v1", ("model_task_input", "v1"), ("source_classification", "v1"), allow_source_excerpt=True),
    TaskSpec("case.extract", "general", "v1", ("model_task_input", "v1"), ("fact_candidates", "v1"), allow_source_excerpt=True),
    TaskSpec("case.model", "general", "v1", ("model_task_input", "v1"), ("case_model", "v1"), allow_source_excerpt=True),
    TaskSpec("editorial.review", "general", "v1", ("model_task_input", "v1"), ("editorial_review", "v1"), allow_source_excerpt=True, user_visible_text=True),
    TaskSpec("image_prompt.refine", "general", "v2", ("model_task_input", "v1"), ("image_prompts", "v2"), user_visible_text=True, invalidates_paid_stages=True),
    TaskSpec(
        "remotion.frame-review",
        "remotion",
        "v1",
        ("model_task_input", "v1"),
        ("frame_review", "v1"),
        max_output_bytes=512_000,
        budget_category="vision_model",
        allow_media=True,
        require_media=True,
        user_visible_text=True,
        semantic_validator="frame_review",
    ),
    TaskSpec("delivery.summarize", "general", "v1", ("model_task_input", "v1"), ("delivery_summary", "v1"), user_visible_text=True),
    TaskSpec("narration.compose", "narration", "v1", ("model_task_input", "v1"), ("editorial", "v1"), max_semantic_revisions=2, allow_source_excerpt=True, user_visible_text=True, invalidates_paid_stages=True, semantic_validator="editorial"),
    TaskSpec("narration.rewrite", "narration", "v1", ("model_task_input", "v1"), ("editorial", "v1"), max_semantic_revisions=2, allow_source_excerpt=True, user_visible_text=True, invalidates_paid_stages=True, semantic_validator="editorial"),
    TaskSpec("remotion.plan", "remotion", "v2", ("model_task_input", "v1"), ("visual_plan", "v2"), max_output_bytes=1_500_000, max_semantic_revisions=2, user_visible_text=True, invalidates_paid_stages=True, semantic_validator="visual_plan"),
    TaskSpec("remotion.repair", "remotion", "v2", ("model_task_input", "v1"), ("visual_plan", "v2"), max_output_bytes=1_500_000, max_semantic_revisions=2, user_visible_text=True, invalidates_paid_stages=True, semantic_validator="visual_plan"),
)


EXPECTED_ROUTES: dict[str, tuple[str, str]] = {
    "narration": ("azure_anthropic", "case-video-claude"),
    "remotion": ("azure_anthropic", "case-video-claude"),
    "general": ("openai", "gpt-5.5"),
}


class TaskRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.prompt_root = (settings.repo_root / "server" / "prompts").resolve()
        self.contracts = ContractRegistry(settings.repo_root / "server" / "schemas")
        self._specs = {spec.name: spec for spec in TASK_SPECS}

    def spec(self, task: str) -> TaskSpec:
        try:
            return self._specs[task]
        except KeyError as exc:
            raise AppError("model_task_unregistered", f"model task is not registered: {task}") from exc

    def route(self, task: str) -> ModelRoute:
        spec = self.spec(task)
        route = self.settings.model_routes[spec.route_family]
        expected_provider, expected_model = EXPECTED_ROUTES[spec.route_family]
        if route.provider.lower() != expected_provider or route.model != expected_model:
            raise AppError(
                "model_route_missing",
                f"{spec.route_family} route must use {expected_provider}/{expected_model}",
                diagnostics={"task": task, "route_family": spec.route_family},
            )
        return route

    def prompt_path(self, spec: TaskSpec) -> Path:
        path = (self.prompt_root / spec.name / spec.prompt_version / "system.txt").resolve()
        if self.prompt_root not in path.parents or not path.is_file():
            raise AppError("contract_invalid", f"prompt not found: {spec.name}/{spec.prompt_version}")
        return path

    def prompt(self, task: str) -> str:
        spec = self.spec(task)
        return self.prompt_path(spec).read_text(encoding="utf-8").strip()

    def prompt_sha256(self, spec: TaskSpec) -> str:
        return hashlib.sha256(self.prompt_path(spec).read_bytes()).hexdigest()

    def validate_input(self, task: str, payload: dict[str, Any]) -> None:
        spec = self.spec(task)
        self.contracts.validate(*spec.input_contract, payload)
        payload_task = payload.get("task")
        if payload_task is not None and payload_task != task:
            raise AppError("contract_invalid", f"input task mismatch: expected {task}, got {payload_task}")
        if payload.get("source_excerpts") and not spec.allow_source_excerpt:
            raise AppError("contract_invalid", f"task does not allow source excerpts: {task}")
        if payload.get("media") and not spec.allow_media:
            raise AppError("contract_invalid", f"task does not allow media: {task}")
        if spec.require_media and not payload.get("media"):
            raise AppError("contract_invalid", f"task requires media: {task}")

    def validate_output(self, task: str, payload: dict[str, Any]) -> None:
        spec = self.spec(task)
        self.contracts.validate(*spec.output_contract, payload, error_code="model_output_invalid")
        validator = _SEMANTIC_VALIDATORS[spec.semantic_validator]
        validator(payload)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for task in sorted(self._specs):
            spec = self._specs[task]
            route = self.route(task)
            input_ref = self.contracts.ref(*spec.input_contract)
            output_ref = self.contracts.ref(*spec.output_contract)
            public_route = route.public_dict()
            snapshot[task] = {
                "task": task,
                "route_family": spec.route_family,
                "provider": public_route["provider"],
                "model": public_route["model"],
                "api_version": public_route["api_version"],
                "transport": public_route["transport"],
                "prompt_version": spec.prompt_version,
                "prompt_sha256": self.prompt_sha256(spec),
                "input_schema": input_ref.public_dict(),
                "output_schema": output_ref.public_dict(),
                "semantic_validator": spec.semantic_validator,
                "timeout_seconds": spec.timeout_seconds,
                "max_output_bytes": spec.max_output_bytes,
                "max_structure_repairs": spec.max_structure_repairs,
                "max_semantic_revisions": spec.max_semantic_revisions,
                "budget_category": spec.budget_category,
                "allow_source_excerpt": spec.allow_source_excerpt,
                "allow_media": spec.allow_media,
                "require_media": spec.require_media,
                "user_visible_text": spec.user_visible_text,
                "invalidates_paid_stages": spec.invalidates_paid_stages,
            }
        return snapshot

    def prompt_pins(self) -> dict[str, dict[str, str]]:
        return {
            task: {
                "version": spec.prompt_version,
                "sha256": self.prompt_sha256(spec),
            }
            for task, spec in sorted(self._specs.items())
        }


def _no_semantic_validation(_: dict[str, Any]) -> None:
    return


def _validate_editorial(payload: dict[str, Any]) -> None:
    text = f"{payload.get('title', '')}\n{payload.get('narration', '')}"
    if "不是" in text and "而是" in text:
        raise AppError("semantic_review_blocked", "editorial output contains prohibited contrast wording")
    if not str(payload.get("title", "")).strip() or not str(payload.get("narration", "")).strip():
        raise AppError("semantic_review_blocked", "editorial output requires a title and narration")


def _is_background_like_asset_id(asset_id: object) -> bool:
    text = str(asset_id or "").strip().lower()
    if not text:
        return False
    return (
        text.startswith(("bg-", "bg_", "background-", "background_"))
        or text.endswith(("-bg", "_bg", "-background", "_background"))
        or "-bg-" in text
        or "_bg_" in text
        or "-background-" in text
        or "_background_" in text
    )


def _validate_visual_plan(payload: dict[str, Any]) -> None:
    scenes = payload.get("scenes", [])
    if not scenes:
        raise AppError("semantic_review_blocked", "visual plan requires at least one scene")
    if payload.get("version") != "2":
        raise AppError("semantic_review_blocked", "director visual plan must use version 2")
    chrome = payload.get("chrome", {})
    if chrome.get("subtitleBar") is not True:
        raise AppError("semantic_review_blocked", "sales director plans must keep subtitleBar enabled")

    planned_scene_ids = [str(scene.get("id", "")) for scene in scenes]
    if len(planned_scene_ids) != len(set(planned_scene_ids)):
        raise AppError("semantic_review_blocked", "visual plan scene ids must be unique")
    planned_scene_id_set = set(planned_scene_ids)

    assets = payload.get("assets", [])
    asset_ids = [str(asset.get("id", "")) for asset in assets]
    if len(asset_ids) != len(set(asset_ids)):
        raise AppError("semantic_review_blocked", "visual plan asset ids must be unique")
    declared_assets = set(asset_ids)
    for asset in assets:
        if str(asset.get("sceneId", "")) not in planned_scene_id_set:
            raise AppError(
                "semantic_review_blocked",
                f"asset {asset.get('id', '')} belongs to an undeclared scene",
            )

    expected_start = 1
    scene_ids: set[str] = set()
    for scene in scenes:
        scene_id = str(scene.get("id", ""))
        if scene_id in scene_ids:
            raise AppError("semantic_review_blocked", f"duplicate visual plan scene id: {scene_id}")
        scene_ids.add(scene_id)
        units = scene.get("units")
        if (
            not isinstance(units, list)
            or len(units) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in units)
        ):
            raise AppError("semantic_review_blocked", "visual plan scenes require [first, last] unit ranges")
        first, last = units
        if first != expected_start or last < first:
            raise AppError("semantic_review_blocked", "visual plan unit ranges must be contiguous and ordered")
        expected_start = last + 1

        if scene.get("visualMode") in {"editorial", "hybrid"} and not scene.get("visualBeats"):
            raise AppError(
                "semantic_review_blocked",
                f"scene {scene_id} uses {scene.get('visualMode')} mode without visual beats",
            )
        if scene.get("visualMode") == "editorial" and scene.get("layout") != "director-canvas":
            raise AppError(
                "semantic_review_blocked",
                f"editorial scene {scene_id} must use director-canvas",
            )
        if scene.get("visualMode") in {"layout", "hybrid"} and scene.get("layout") == "director-canvas":
            raise AppError(
                "semantic_review_blocked",
                f"{scene.get('visualMode')} scene {scene_id} must choose an explicit layout",
            )
        if scene.get("visualMode") in {"layout", "hybrid"} and (
            "tone" not in scene or "headline" not in scene
        ):
            raise AppError(
                "semantic_review_blocked",
                f"{scene.get('visualMode')} scene {scene_id} requires tone and headline",
            )
        if scene.get("layout") == "director-canvas" and any(
            keyword.get("display") is True for keyword in scene.get("keywords", [])
        ):
            raise AppError(
                "semantic_review_blocked",
                f"director-canvas scene {scene_id} must render visible keywords as explicit text layers",
            )
        if scene.get("chrome", {}).get("subtitleBar") is False:
            raise AppError(
                "semantic_review_blocked",
                f"scene {scene_id} cannot disable the required subtitle bar",
            )
        previous_keyword = first - 1
        for keyword in scene.get("keywords", []):
            at_unit = int(keyword.get("atUnit", 0))
            if at_unit < previous_keyword or at_unit > last:
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} keywords must be ordered inside the scene",
                )
            previous_keyword = at_unit
        previous_background = first - 1
        for background in scene.get("backgrounds", []):
            if background.get("asset") not in declared_assets:
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} references undeclared background asset",
                )
            if not first <= int(background.get("atUnit", 0)) <= last:
                raise AppError("semantic_review_blocked", f"scene {scene_id} background is outside its unit range")
            if int(background.get("atUnit", 0)) <= previous_background:
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} backgrounds must be strictly ordered",
                )
            previous_background = int(background["atUnit"])
        previous_beat = first - 1
        for beat_position, beat in enumerate(scene.get("visualBeats", []), start=1):
            at_unit = int(beat.get("atUnit", 0))
            if at_unit <= previous_beat or at_unit > last:
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} visual beats must be ordered inside the scene",
                )
            previous_beat = at_unit
            if beat_position == 1 and scene.get("visualMode") in {"editorial", "hybrid"} and at_unit != first:
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} first visual beat must start at the scene's first unit",
                )
            if beat.get("chrome", {}).get("subtitleBar") is False:
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} beat {beat_position} cannot disable the required subtitle bar",
                )
            base_asset_id = beat.get("baseAsset")
            if base_asset_id and base_asset_id not in declared_assets:
                raise AppError("semantic_review_blocked", f"scene {scene_id} beat references undeclared asset")
            if base_asset_id and _is_background_like_asset_id(base_asset_id):
                canvas_tone = beat.get("render", {}).get("canvasTone")
                if canvas_tone != "transparent":
                    raise AppError(
                        "semantic_review_blocked",
                        f"scene {scene_id} beat {beat_position} uses background-like baseAsset "
                        f"{base_asset_id!r} with canvasTone {canvas_tone!r}; keep the generated "
                        "background visible with canvasTone 'transparent' and use tint, overlay, "
                        "or bounded text layers for readability",
                    )
            _validate_director_box(beat.get("baseBox"), f"scene {scene_id} beat baseBox")
            if (
                not beat.get("baseAsset")
                and not beat.get("layers")
                and beat.get("render", {}).get("canvasTone") == "transparent"
                and not beat.get("chrome")
            ):
                raise AppError(
                    "semantic_review_blocked",
                    f"scene {scene_id} beat {beat_position} does not change any visible pixels",
                )
            for layer in beat.get("layers", []):
                if layer.get("asset") and layer.get("asset") not in declared_assets:
                    raise AppError("semantic_review_blocked", f"scene {scene_id} layer references undeclared asset")
                _validate_director_box(layer.get("box"), f"scene {scene_id} layer box")
                if (
                    layer.get("kind") == "text"
                    and layer.get("surface") in {"paper", "solid", "accent"}
                    and layer.get("box") is None
                ):
                    raise AppError(
                        "semantic_review_blocked",
                        f"scene {scene_id} beat {beat_position} text layer uses {layer.get('surface')!r} "
                        "surface without an explicit box; use compact glass/none text on a slot "
                        "or bind opaque card surfaces to a declared box",
                    )
                for timing_key in ("revealAtUnit", "exitAtUnit"):
                    timing = layer.get(timing_key)
                    if timing is not None and not first <= int(timing) <= last:
                        raise AppError(
                            "semantic_review_blocked",
                            f"scene {scene_id} layer {timing_key} is outside its unit range",
                        )
                reveal_at = int(layer.get("revealAtUnit", at_unit))
                if reveal_at < at_unit:
                    raise AppError(
                        "semantic_review_blocked",
                        f"scene {scene_id} layer cannot reveal before its visual beat",
                    )
                if layer.get("exitAtUnit") is not None and int(layer["exitAtUnit"]) < reveal_at:
                    raise AppError(
                        "semantic_review_blocked",
                        f"scene {scene_id} layer cannot exit before it reveals",
                    )
                for nested_key in ("bars", "nodes", "links"):
                    for nested in layer.get(nested_key, []):
                        if nested_key == "nodes" and nested.get("asset") not in {None, ""}:
                            if nested["asset"] not in declared_assets:
                                raise AppError(
                                    "semantic_review_blocked",
                                    f"scene {scene_id} network node references undeclared asset",
                                )
                        if nested.get("revealAtUnit") is not None and int(nested["revealAtUnit"]) < at_unit:
                            raise AppError(
                                "semantic_review_blocked",
                                f"scene {scene_id} nested layer item cannot reveal before its visual beat",
                            )


def _validate_director_box(value: Any, label: str) -> None:
    if value is None:
        return
    x = float(value["x"])
    y = float(value["y"])
    width = float(value["width"])
    height = float(value["height"])
    if x + width > 1.000001 or y + height > 1.000001:
        raise AppError("semantic_review_blocked", f"{label} must stay inside the normalized canvas")


def _validate_frame_review(payload: dict[str, Any]) -> None:
    issues = payload.get("issues", [])
    issue_ids = [str(issue.get("issue_id", "")) for issue in issues]
    if len(issue_ids) != len(set(issue_ids)):
        raise AppError("semantic_review_blocked", "frame review issue ids must be unique")
    material = [issue for issue in issues if issue.get("severity") in {"blocker", "major"}]
    verdict = payload.get("verdict")
    if verdict == "pass" and material:
        raise AppError("semantic_review_blocked", "frame review cannot pass with blocker or major issues")
    if verdict == "revise" and not material:
        raise AppError("semantic_review_blocked", "frame review revise verdict requires a blocker or major issue")


_SEMANTIC_VALIDATORS: dict[str, SemanticValidator] = {
    "none": _no_semantic_validation,
    "editorial": _validate_editorial,
    "visual_plan": _validate_visual_plan,
    "frame_review": _validate_frame_review,
}
