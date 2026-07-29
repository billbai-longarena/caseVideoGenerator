#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.app.services.visual_adapter import build_rich_storyboard


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_authored_title(project: Path) -> str | None:
    path = project / "title.txt"
    if not path.is_file():
        print(
            "warning: title.txt is missing; using the legacy title embedded in storyboard_plan.json",
            file=sys.stderr,
        )
        return None

    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise SystemExit("title.txt must contain exactly one non-empty logical line")
    return lines[0].strip()


def display_text(text: str, replacements: dict[str, str]) -> str:
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def bounded_unit(first: int, last: int, offset: int) -> int:
    return min(last, max(first, first + int(offset)))


def relative_unit(first: int, last: int, offset: object, label: str) -> int:
    try:
        unit = first + int(offset)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{label} offset must be an integer: {offset!r}") from exc
    if unit < first or unit > last:
        raise SystemExit(
            f"{label} offset resolves to unit {unit}, outside scene units [{first}, {last}]"
        )
    return unit


def absolute_or_relative_unit(
    value: dict,
    *,
    first: int,
    last: int,
    absolute_key: str,
    relative_key: str,
    label: str,
    default_offset: int | None = None,
) -> int | None:
    if absolute_key in value and relative_key in value:
        raise SystemExit(f"{label} cannot define both {absolute_key} and {relative_key}")
    if absolute_key in value:
        unit = value[absolute_key]
        if not isinstance(unit, int):
            raise SystemExit(f"{label} {absolute_key} must be an integer")
        if unit < first or unit > last:
            raise SystemExit(
                f"{label} {absolute_key}={unit} is outside scene units [{first}, {last}]"
            )
        return unit
    if relative_key in value:
        return relative_unit(first, last, value[relative_key], label)
    if default_offset is not None:
        return relative_unit(first, last, default_offset, label)
    return None


def build_visual_beats(
    spec: dict,
    *,
    scene_id: str,
    first: int,
    last: int,
) -> list[dict]:
    raw_beats = spec.get("visualBeats")
    if raw_beats is None:
        return []
    if not isinstance(raw_beats, list) or not raw_beats:
        raise SystemExit(f"scene {scene_id} visualBeats must be a non-empty list")

    beats: list[dict] = []
    for beat_position, raw_beat in enumerate(raw_beats, start=1):
        if not isinstance(raw_beat, dict):
            raise SystemExit(f"scene {scene_id} visual beat {beat_position} must be an object")
        beat = deepcopy(raw_beat)
        beat_label = f"scene {scene_id} visual beat {beat_position}"
        beat["id"] = beat.get("id", f"{scene_id}-b{beat_position:02d}")
        beat["atUnit"] = absolute_or_relative_unit(
            beat,
            first=first,
            last=last,
            absolute_key="atUnit",
            relative_key="offset",
            label=beat_label,
            default_offset=0,
        )
        beat.pop("offset", None)

        raw_layers = beat.get("layers", [])
        if not isinstance(raw_layers, list):
            raise SystemExit(f"{beat_label} layers must be a list")
        layers: list[dict] = []
        for layer_position, raw_layer in enumerate(raw_layers, start=1):
            if not isinstance(raw_layer, dict):
                raise SystemExit(f"{beat_label} layer {layer_position} must be an object")
            layer = deepcopy(raw_layer)
            layer_label = f"{beat_label} layer {layer_position}"
            layer["id"] = layer.get("id", f"{beat['id']}-l{layer_position:02d}")
            reveal = absolute_or_relative_unit(
                layer,
                first=first,
                last=last,
                absolute_key="revealAtUnit",
                relative_key="revealOffset",
                label=layer_label,
            )
            exit_unit = absolute_or_relative_unit(
                layer,
                first=first,
                last=last,
                absolute_key="exitAtUnit",
                relative_key="exitOffset",
                label=layer_label,
            )
            layer.pop("revealOffset", None)
            layer.pop("exitOffset", None)
            if reveal is not None:
                layer["revealAtUnit"] = reveal
            if exit_unit is not None:
                layer["exitAtUnit"] = exit_unit
            # Nested reveal timings inside data-driven layers (bar-compare bars,
            # network nodes/links) accept the same offset->unit conversion.
            for nested_key in ("bars", "nodes", "links"):
                nested_items = layer.get(nested_key)
                if not isinstance(nested_items, list):
                    continue
                for nested_position, nested in enumerate(nested_items, start=1):
                    if not isinstance(nested, dict):
                        raise SystemExit(
                            f"{layer_label} {nested_key} item {nested_position} must be an object"
                        )
                    nested_reveal = absolute_or_relative_unit(
                        nested,
                        first=first,
                        last=last,
                        absolute_key="revealAtUnit",
                        relative_key="revealOffset",
                        label=f"{layer_label} {nested_key} item {nested_position}",
                    )
                    nested.pop("revealOffset", None)
                    if nested_reveal is not None:
                        nested["revealAtUnit"] = nested_reveal
            layers.append(layer)
        beat["layers"] = layers
        beats.append(beat)
    return beats


def build_cover(
    project_meta: dict,
    *,
    first: int,
    last: int,
    authored_title: str | None = None,
) -> dict:
    raw_cover = project_meta.get("cover", {})
    if raw_cover is None:
        raw_cover = {}
    if not isinstance(raw_cover, dict):
        raise SystemExit("project.cover must be an object")

    title = authored_title or raw_cover.get("title", project_meta.get("title"))
    if not isinstance(title, str) or not title.strip():
        raise SystemExit("project.cover.title must be a non-empty string")

    through_unit = raw_cover.get("throughUnit", first)
    if isinstance(through_unit, bool) or not isinstance(through_unit, int):
        raise SystemExit("project.cover.throughUnit must be an integer")
    if through_unit < first or through_unit > last:
        raise SystemExit(
            f"project.cover.throughUnit={through_unit} is outside first scene units "
            f"[{first}, {last}]"
        )

    cover = {"title": title.strip(), "throughUnit": through_unit}
    for key, fallback in (
        ("subtitle", project_meta.get("subtitle")),
        ("kicker", project_meta.get("brand")),
    ):
        value = raw_cover[key] if key in raw_cover else fallback
        if value is None:
            continue
        if not isinstance(value, str):
            raise SystemExit(f"project.cover.{key} must be a string")
        cover[key] = value.strip()
    return cover


def scene_paragraphs(spec: dict, position: int) -> list[int]:
    if "paragraph" in spec and "paragraphs" in spec:
        raise SystemExit("scene cannot define both paragraph and paragraphs")
    if "paragraphs" not in spec:
        return [int(spec.get("paragraph", position))]

    raw = spec["paragraphs"]
    if not isinstance(raw, list) or not raw:
        raise SystemExit("scene paragraphs must be a non-empty list")
    if len(raw) == 2 and all(isinstance(item, int) for item in raw) and raw[0] <= raw[1]:
        return list(range(raw[0], raw[1] + 1))
    paragraphs: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int):
            raise SystemExit(f"scene paragraphs entries must be integers: {item!r}")
        paragraphs.append(item)
    return paragraphs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rich_storyboard.json from a paragraph-based plan.")
    parser.add_argument("project", help="Case-video project directory")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    timeline = load_json(project / "narration.timeline.json")
    plan = load_json(project / "storyboard_plan.json")
    authored_title = load_authored_title(project)
    if (
        plan.get("version") in {"1", "2"}
        and isinstance(plan.get("scenes"), list)
        and plan["scenes"]
        and isinstance(plan["scenes"][0], dict)
        and ("scene_id" in plan["scenes"][0] or "units" in plan["scenes"][0])
    ):
        if authored_title is None:
            raise SystemExit("title.txt is required for a contracted visual plan")
        prompt_path = project / "image_prompts.json"
        image_prompts = load_json(prompt_path) if prompt_path.is_file() else None
        try:
            storyboard = build_rich_storyboard(
                plan,
                timeline,
                authored_title=authored_title,
                project_name=project.name,
                program=str(plan.get("subtitleLabel") or "销售不复杂"),
                image_prompts=image_prompts,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        output = project / "rich_storyboard.json"
        output.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {output} scenes={len(storyboard['scenes'])} units={len(timeline['units'])}")
        return
    units = timeline["units"]
    by_paragraph: dict[int, list[dict]] = {}
    for unit in units:
        by_paragraph.setdefault(int(unit["paragraph"]), []).append(unit)

    replacements = plan.get("displayReplacements", {})
    scenes = []
    for position, spec in enumerate(plan["scenes"], start=1):
        paragraph_indexes = scene_paragraphs(spec, position)
        paragraph_units = []
        for paragraph in paragraph_indexes:
            current = by_paragraph.get(paragraph)
            if not current:
                raise SystemExit(f"no timeline units for paragraph {paragraph}")
            paragraph_units.extend(current)
        first = int(paragraph_units[0]["index"])
        last = int(paragraph_units[-1]["index"])

        props = dict(spec.get("props", {}))
        for key, offset in spec.get("propTimings", {}).items():
            if isinstance(offset, list):
                props[key] = [bounded_unit(first, last, item) for item in offset]
            else:
                props[key] = bounded_unit(first, last, offset)

        keywords = []
        for keyword in spec.get("keywords", []):
            cue = {"text": keyword["text"], "atUnit": bounded_unit(first, last, keyword.get("offset", 0))}
            if keyword.get("sfx"):
                cue["sfx"] = keyword["sfx"]
            keywords.append(cue)

        background = {
            "atUnit": first,
            "transition": spec.get("transition", "wash"),
            "motion": spec.get("motion", "center"),
        }
        if "backgroundVideo" in spec:
            background["video"] = spec["backgroundVideo"]
        else:
            background["image"] = spec["background"]

        scene_id = spec.get("id", f"s{position:02d}")
        scene = {
            "id": scene_id,
            "chapter": spec.get("chapter", f"{position:02d}"),
            "kicker": spec["kicker"],
            "layout": spec["layout"],
            "tone": spec.get("tone", "dark"),
            "units": [first, last],
            "headline": {"text": spec["headline"], "reveal": spec.get("reveal", "perClause"), "accent": spec.get("accent", [])},
            "keywords": keywords,
            "subtitles": [
                {"unit": int(unit["index"]), "text": display_text(unit["text"], replacements)}
                for unit in paragraph_units
            ],
            "backgrounds": [background],
            "props": props,
        }
        if "allowBackgroundReuse" in spec:
            scene["allowBackgroundReuse"] = bool(spec["allowBackgroundReuse"])
        visual_beats = build_visual_beats(
            spec,
            scene_id=scene_id,
            first=first,
            last=last,
        )
        if visual_beats:
            scene["visualMode"] = spec.get("visualMode", "editorial")
            scene["visualBeats"] = visual_beats
        elif "visualMode" in spec:
            scene["visualMode"] = spec["visualMode"]
        scenes.append(scene)

    project_meta = deepcopy(plan["project"])
    if authored_title is not None:
        project_meta["title"] = authored_title

    first_scene_first, first_scene_last = scenes[0]["units"]
    cover = build_cover(
        project_meta,
        first=first_scene_first,
        last=first_scene_last,
        authored_title=authored_title,
    )
    storyboard = {
        **project_meta,
        "cover": cover,
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "audio": "audio/narration_azure.wav",
        "timeline": "narration.timeline.json",
        "duration": timeline["duration"],
        "scenes": scenes,
    }
    if "visualAssets" in plan:
        storyboard["visualAssets"] = deepcopy(plan["visualAssets"])
    output = project / "rich_storyboard.json"
    output.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} scenes={len(scenes)} units={len(units)}")


if __name__ == "__main__":
    main()
