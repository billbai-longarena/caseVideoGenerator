from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from pathlib import PurePosixPath
from typing import Any


LAYOUT_MAP = {
    "cover": "breaking-news",
    "hero": "subject-reveal",
    "split": "insight-split",
    "quote": "closing-quote",
    "comparison": "split-data",
    "timeline": "timeline-roadshow",
    "evidence": "reveal-card",
    "summary": "closing-idea",
}

TRANSITIONS = ("wash", "paper", "ink", "push")
MOTIONS = ("center", "left", "right", "drift", "breathe", "lift")


def safe_scene_stem(scene_id: str) -> str:
    """Return a deterministic, path-safe stem without trusting model text."""

    normalized = re.sub(r"[^A-Za-z0-9]+", "-", scene_id.strip().lower()).strip("-")
    slug = (normalized or "scene")[:40]
    digest = hashlib.sha256(scene_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def scene_image_path(scene_id: str) -> str:
    return f"images/generated/{safe_scene_stem(scene_id)}.png"


def prompt_image_path(record: dict[str, Any]) -> str | None:
    """Resolve legacy files plus scene-addressed v1 and asset-addressed v2 prompts."""

    legacy = record.get("file") or record.get("src")
    if isinstance(legacy, str) and legacy.strip():
        normalized = legacy.replace("\\", "/").strip()
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or ".." in pure.parts:
            return None
        return pure.as_posix()
    prompt_id = record.get("asset_id") or record.get("scene_id")
    if isinstance(prompt_id, str) and prompt_id.strip():
        return scene_image_path(prompt_id)
    return None


def build_rich_storyboard(
    plan: dict[str, Any],
    timeline: dict[str, Any],
    *,
    authored_title: str,
    project_name: str = "",
    program: str = "销售不复杂",
    image_prompts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a visual plan without inventing creative choices in the adapter."""

    version = str(plan.get("version", ""))
    if version == "2":
        return _build_v2_rich_storyboard(
            plan,
            timeline,
            authored_title=authored_title,
            project_name=project_name,
            program=program,
            image_prompts=image_prompts,
        )
    if version == "1":
        return _build_v1_rich_storyboard(
            plan,
            timeline,
            authored_title=authored_title,
            project_name=project_name,
            program=program,
            image_prompts=image_prompts,
        )
    raise ValueError(f"unsupported visual plan version: {version or 'missing'}")


def _timeline_units(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    units = timeline.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("timeline.units must be a non-empty list")
    indices = [unit.get("index") for unit in units if isinstance(unit, dict)]
    expected_indices = list(range(1, len(units) + 1))
    if indices != expected_indices:
        raise ValueError(f"timeline units must be continuous 1..{len(units)}")
    return units


def _unit_in_scene(value: Any, first: int, last: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < first or value > last:
        raise ValueError(f"{label} must be inside scene units [{first}, {last}]")
    return value


def _validate_box(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    try:
        x = float(value["x"])
        y = float(value["y"])
        width = float(value["width"])
        height = float(value["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} requires numeric x, y, width and height") from exc
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
        raise ValueError(f"{label} must stay inside the normalized canvas")


def _build_v2_rich_storyboard(
    plan: dict[str, Any],
    timeline: dict[str, Any],
    *,
    authored_title: str,
    project_name: str,
    program: str,
    image_prompts: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compile the director DSL by validation, asset resolution and data copying only."""

    units = _timeline_units(timeline)
    if plan.get("cover", {}).get("title") != authored_title:
        raise ValueError("visual plan cover title must exactly match title.txt")
    if plan.get("subtitleLabel") != program:
        raise ValueError(f"visual plan subtitleLabel must be {program}")
    if plan.get("chrome", {}).get("subtitleBar") is not True:
        raise ValueError("visual plan must keep subtitleBar enabled")

    raw_assets = plan.get("assets")
    if not isinstance(raw_assets, list):
        raise ValueError("visual_plan/v2 assets must be an array")
    visual_assets: list[dict[str, Any]] = []
    assets_by_id: dict[str, dict[str, Any]] = {}
    for position, raw_asset in enumerate(raw_assets, start=1):
        if not isinstance(raw_asset, dict):
            raise ValueError(f"visual asset {position} must be an object")
        asset_id = str(raw_asset.get("id", "")).strip()
        if not asset_id or asset_id in assets_by_id:
            raise ValueError(f"visual asset ids must be non-empty and unique: {asset_id!r}")
        assets_by_id[asset_id] = raw_asset
        visual_assets.append(
            {
                "id": asset_id,
                "type": "image",
                "src": scene_image_path(asset_id),
                "role": str(raw_asset["role"]),
                "origin": "generated",
            }
        )

    prompt_records = image_prompts.get("prompts", []) if isinstance(image_prompts, dict) else []
    if prompt_records:
        prompt_ids = [
            str(record.get("asset_id") or record.get("scene_id") or "")
            for record in prompt_records
            if isinstance(record, dict)
        ]
        if len(prompt_ids) != len(set(prompt_ids)) or set(prompt_ids) != set(assets_by_id):
            raise ValueError("image prompts must address every declared asset exactly once")

    timeline_by_index = {int(unit["index"]): unit for unit in units}
    plan_scenes = plan.get("scenes")
    if not isinstance(plan_scenes, list) or not plan_scenes:
        raise ValueError("visual plan requires at least one scene")
    planned_scene_ids = [str(scene.get("id", "")).strip() for scene in plan_scenes if isinstance(scene, dict)]
    if len(planned_scene_ids) != len(plan_scenes) or len(planned_scene_ids) != len(set(planned_scene_ids)):
        raise ValueError("visual plan scene ids must be non-empty and unique")
    planned_scene_id_set = set(planned_scene_ids)
    for asset_id, raw_asset in assets_by_id.items():
        if str(raw_asset.get("sceneId", "")).strip() not in planned_scene_id_set:
            raise ValueError(f"visual asset {asset_id!r} belongs to an undeclared scene")

    scenes: list[dict[str, Any]] = []
    expected_first = 1
    seen_scene_ids: set[str] = set()
    used_backgrounds: set[str] = set()
    for position, spec in enumerate(plan_scenes, start=1):
        if not isinstance(spec, dict):
            raise ValueError(f"visual plan scene {position} must be an object")
        scene_id = str(spec.get("id", "")).strip()
        if not scene_id or scene_id in seen_scene_ids:
            raise ValueError(f"scene ids must be non-empty and unique: {scene_id!r}")
        seen_scene_ids.add(scene_id)
        raw_range = spec.get("units")
        if (
            not isinstance(raw_range, list)
            or len(raw_range) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in raw_range)
        ):
            raise ValueError(f"scene {scene_id} requires a [first, last] unit range")
        first, last = raw_range
        if first != expected_first or last < first or last > len(units):
            raise ValueError("visual plan scenes must be ordered and cover every timeline unit")
        expected_first = last + 1

        backgrounds: list[dict[str, Any]] = []
        previous_background_unit = first - 1
        repeated_background = False
        for background_position, raw_background in enumerate(spec.get("backgrounds", []), start=1):
            asset_id = str(raw_background.get("asset", ""))
            if asset_id not in assets_by_id:
                raise ValueError(f"scene {scene_id} background references undeclared asset {asset_id!r}")
            at_unit = _unit_in_scene(
                raw_background.get("atUnit"),
                first,
                last,
                f"scene {scene_id} background {background_position} atUnit",
            )
            if at_unit <= previous_background_unit:
                raise ValueError(f"scene {scene_id} backgrounds must be ordered by atUnit")
            previous_background_unit = at_unit
            background = {
                "image": scene_image_path(asset_id),
                "atUnit": at_unit,
                "transition": raw_background["transition"],
                "motion": raw_background["motion"],
            }
            if raw_background.get("sfx"):
                background["sfx"] = raw_background["sfx"]
            repeated_background = repeated_background or background["image"] in used_backgrounds
            used_backgrounds.add(background["image"])
            backgrounds.append(background)
        keywords: list[dict[str, Any]] = []
        previous_keyword_unit = first - 1
        for keyword_position, raw_keyword in enumerate(spec.get("keywords", []), start=1):
            keyword_unit = _unit_in_scene(
                raw_keyword.get("atUnit"),
                first,
                last,
                f"scene {scene_id} keyword {keyword_position} atUnit",
            )
            if keyword_unit < previous_keyword_unit:
                raise ValueError(f"scene {scene_id} keywords must be ordered by atUnit")
            previous_keyword_unit = keyword_unit
            cue = deepcopy(raw_keyword)
            cue["text"] = str(raw_keyword["text"])
            cue["atUnit"] = keyword_unit
            keywords.append(cue)

        visual_beats = deepcopy(spec.get("visualBeats", []))
        visual_mode = spec.get("visualMode")
        if visual_mode in {"editorial", "hybrid"} and not visual_beats:
            raise ValueError(f"scene {scene_id} requires visual beats for {visual_mode} mode")
        if visual_mode == "editorial" and spec.get("layout") != "director-canvas":
            raise ValueError(f"editorial scene {scene_id} must use director-canvas")
        if visual_mode in {"layout", "hybrid"} and spec.get("layout") == "director-canvas":
            raise ValueError(f"{visual_mode} scene {scene_id} must choose an explicit layout")
        if visual_mode in {"layout", "hybrid"} and ("tone" not in spec or "headline" not in spec):
            raise ValueError(f"{visual_mode} scene {scene_id} requires tone and headline")
        if spec.get("chrome", {}).get("subtitleBar") is False:
            raise ValueError(f"scene {scene_id} cannot disable the required subtitle bar")
        previous_beat_unit = first - 1
        for beat_position, beat in enumerate(visual_beats, start=1):
            beat_unit = _unit_in_scene(
                beat.get("atUnit"), first, last, f"scene {scene_id} beat {beat_position} atUnit"
            )
            if beat_unit <= previous_beat_unit:
                raise ValueError(f"scene {scene_id} visual beats must be strictly ordered")
            previous_beat_unit = beat_unit
            if beat_position == 1 and visual_mode in {"editorial", "hybrid"} and beat_unit != first:
                raise ValueError(f"scene {scene_id} first visual beat must start at the scene's first unit")
            if beat.get("chrome", {}).get("subtitleBar") is False:
                raise ValueError(f"scene {scene_id} beat {beat_position} cannot disable the required subtitle bar")
            base_asset = beat.get("baseAsset")
            if base_asset and base_asset not in assets_by_id:
                raise ValueError(f"scene {scene_id} beat references undeclared asset {base_asset!r}")
            _validate_box(beat.get("baseBox"), f"scene {scene_id} beat {beat_position} baseBox")
            if (
                not base_asset
                and not beat.get("layers")
                and beat.get("render", {}).get("canvasTone") == "transparent"
                and not beat.get("chrome")
            ):
                raise ValueError(f"scene {scene_id} beat {beat_position} does not change any visible pixels")
            for layer_position, layer in enumerate(beat.get("layers", []), start=1):
                layer_asset = layer.get("asset")
                if layer_asset and layer_asset not in assets_by_id:
                    raise ValueError(
                        f"scene {scene_id} beat {beat_position} layer references undeclared asset {layer_asset!r}"
                    )
                _validate_box(
                    layer.get("box"),
                    f"scene {scene_id} beat {beat_position} layer {layer_position} box",
                )
                reveal_unit = _unit_in_scene(
                    layer.get("revealAtUnit", beat_unit),
                    first,
                    last,
                    f"scene {scene_id} beat {beat_position} layer {layer_position} revealAtUnit",
                )
                if reveal_unit < beat_unit:
                    raise ValueError(
                        f"scene {scene_id} beat {beat_position} layer {layer_position} cannot reveal before its beat"
                    )
                if "exitAtUnit" in layer:
                    exit_unit = _unit_in_scene(
                        layer["exitAtUnit"],
                        first,
                        last,
                        f"scene {scene_id} beat {beat_position} layer {layer_position} exitAtUnit",
                    )
                    if exit_unit < reveal_unit:
                        raise ValueError(
                            f"scene {scene_id} beat {beat_position} layer {layer_position} exits before it reveals"
                        )
                for nested_key in ("bars", "nodes", "links"):
                    for nested_position, nested in enumerate(layer.get(nested_key, []), start=1):
                        if nested_key == "nodes" and nested.get("asset") and nested["asset"] not in assets_by_id:
                            raise ValueError(
                                f"scene {scene_id} network node references undeclared asset {nested['asset']!r}"
                            )
                        if "revealAtUnit" in nested:
                            nested_reveal = _unit_in_scene(
                                nested["revealAtUnit"],
                                first,
                                last,
                                f"scene {scene_id} {nested_key} item {nested_position} revealAtUnit",
                            )
                            if nested_reveal < beat_unit:
                                raise ValueError(
                                    f"scene {scene_id} {nested_key} item {nested_position} cannot reveal before its beat"
                                )

        scene_units = [timeline_by_index[index] for index in range(first, last + 1)]
        scene: dict[str, Any] = {
            "id": scene_id,
            "chapter": str(spec.get("chapter", "")),
            "kicker": str(spec.get("kicker", "")),
            "layout": spec["layout"],
            "units": [first, last],
            "dramaticFunction": str(spec["dramaticFunction"]),
            "directorialIntent": str(spec["directorialIntent"]),
            "keywords": keywords,
            "subtitles": [
                {"unit": int(unit["index"]), "text": str(unit.get("text", ""))}
                for unit in scene_units
            ],
            "backgrounds": backgrounds,
            "visualMode": spec["visualMode"],
            "visualBeats": visual_beats,
            "sceneMotion": deepcopy(spec["sceneMotion"]),
            "transition": spec["transition"],
            "transitionFrames": spec["transitionFrames"],
            "props": deepcopy(spec.get("layoutProps", {})),
        }
        if "tone" in spec:
            scene["tone"] = spec["tone"]
        if "headline" in spec:
            scene["headline"] = deepcopy(spec["headline"])
        if spec.get("chrome") is not None:
            scene["chrome"] = deepcopy(spec["chrome"])
        if repeated_background:
            scene["allowBackgroundReuse"] = True
        scenes.append(scene)

    if expected_first != len(units) + 1:
        raise ValueError("visual plan scenes must cover every timeline unit")
    first_scene_first, first_scene_last = scenes[0]["units"]
    through_unit = plan["cover"]["throughUnit"]
    if through_unit < first_scene_first or through_unit > first_scene_last:
        raise ValueError("visual plan cover throughUnit must be inside the first scene")

    cover = {
        key: deepcopy(value)
        for key, value in plan["cover"].items()
        if key in {"title", "subtitle", "kicker", "throughUnit"}
    }
    return {
        "slug": project_name,
        "title": authored_title,
        "subtitle": str(plan["cover"].get("subtitle", "")),
        "brand": str(plan.get("brand") or program),
        "projectType": plan["projectType"],
        "visualStyle": str(plan["visualStyle"]),
        "subtitleLabel": str(plan.get("subtitleLabel") or program),
        "directorPlanVersion": "2",
        "direction": deepcopy(plan["direction"]),
        "chrome": deepcopy(plan["chrome"]),
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "audio": "audio/narration_azure.wav",
        "timeline": "narration.timeline.json",
        "duration": float(timeline.get("duration") or units[-1].get("end") or 0),
        "cover": cover,
        "visualAssets": visual_assets,
        "scenes": scenes,
    }


def _build_v1_rich_storyboard(
    plan: dict[str, Any],
    timeline: dict[str, Any],
    *,
    authored_title: str,
    project_name: str = "",
    program: str = "销售不复杂",
    image_prompts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility compiler for the constrained visual_plan/v1 contract."""

    units = _timeline_units(timeline)
    expected_indices = list(range(1, len(units) + 1))

    plan_scenes = plan.get("scenes")
    if not isinstance(plan_scenes, list) or not plan_scenes:
        raise ValueError("visual plan requires at least one scene")

    prompt_records = (
        image_prompts.get("prompts", [])
        if isinstance(image_prompts, dict)
        else []
    )
    style_families = {
        str(record.get("style_family"))
        for record in prompt_records
        if isinstance(record, dict) and record.get("style_family")
    }
    management_style = "sales-management-silhouette" in style_families
    visual_style = (
        "warm manager silhouettes, navy and burnt orange cut-paper screen-print"
        if management_style
        else "bright blue and yellow editorial watercolor"
    )

    timeline_by_index = {int(unit["index"]): unit for unit in units}
    scenes: list[dict[str, Any]] = []
    covered: list[int] = []
    previous_background: str | None = None
    for position, spec in enumerate(plan_scenes, start=1):
        if not isinstance(spec, dict):
            raise ValueError(f"visual plan scene {position} must be an object")
        scene_id = str(spec.get("scene_id", "")).strip()
        if not scene_id:
            raise ValueError(f"visual plan scene {position} requires scene_id")
        at_unit = spec.get("atUnit")
        unit_count = spec.get("units")
        if isinstance(at_unit, bool) or not isinstance(at_unit, int) or at_unit < 0:
            raise ValueError(f"scene {scene_id} has invalid atUnit")
        if isinstance(unit_count, bool) or not isinstance(unit_count, int) or unit_count < 1:
            raise ValueError(f"scene {scene_id} has invalid units")
        first = at_unit + 1
        last = first + unit_count - 1
        if first < 1 or last > len(units):
            raise ValueError(f"scene {scene_id} resolves outside timeline units")
        covered.extend(range(first, last + 1))

        intentional_reuse = bool(spec.get("reuse") or spec.get("allowBackgroundReuse"))
        background = previous_background if intentional_reuse and previous_background else scene_image_path(scene_id)
        previous_background = background

        raw_keywords = spec.get("keywords", [])
        keywords: list[dict[str, Any]] = []
        if isinstance(raw_keywords, list):
            denominator = max(1, len(raw_keywords))
            for keyword_position, keyword in enumerate(raw_keywords):
                text = str(keyword).strip()
                if not text:
                    continue
                offset = min(unit_count - 1, (keyword_position * unit_count) // denominator)
                keywords.append({"text": text, "atUnit": first + offset})

        scene_units = [timeline_by_index[index] for index in range(first, last + 1)]
        scene: dict[str, Any] = {
            "id": scene_id,
            "chapter": f"{position:02d}",
            "kicker": str(spec.get("kicker") or program),
            "layout": LAYOUT_MAP[str(spec["layout"])],
            "tone": "dark" if management_style else "bright",
            "units": [first, last],
            "headline": {
                "text": str(spec["headline"]),
                "reveal": "perClause",
                "accent": [item["text"] for item in keywords[:2]],
            },
            "keywords": keywords,
            "subtitles": [
                {"unit": int(unit["index"]), "text": str(unit.get("text", ""))}
                for unit in scene_units
            ],
            "backgrounds": [
                {
                    "image": background,
                    "atUnit": first,
                    "transition": TRANSITIONS[(position - 1) % len(TRANSITIONS)],
                    "motion": MOTIONS[(position - 1) % len(MOTIONS)],
                }
            ],
            "visualMode": "layout",
            "props": {"visualIntent": str(spec.get("visual_intent", ""))},
        }
        if intentional_reuse:
            scene["allowBackgroundReuse"] = True
        scenes.append(scene)

    if covered != expected_indices:
        raise ValueError(
            "visual plan scenes must be ordered, non-overlapping, and cover every timeline unit"
        )
    if plan.get("cover", {}).get("title") != authored_title:
        raise ValueError("visual plan cover title must exactly match title.txt")

    first_scene_first = int(scenes[0]["units"][0])
    return {
        "slug": project_name,
        "title": authored_title,
        "subtitle": "",
        "brand": str(plan.get("brand") or program),
        "projectType": "sales-management" if management_style else "sales",
        "visualStyle": visual_style,
        "subtitleLabel": str(plan.get("subtitleLabel") or program),
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "audio": "audio/narration_azure.wav",
        "timeline": "narration.timeline.json",
        "duration": float(timeline.get("duration") or units[-1].get("end") or 0),
        "cover": {
            "title": authored_title,
            "kicker": str(plan.get("brand") or program),
            "throughUnit": first_scene_first,
        },
        "scenes": scenes,
    }
