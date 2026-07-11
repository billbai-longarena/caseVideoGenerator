#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

FORBIDDEN_BACKGROUND_MARKERS = (
    "images/management_cutout/",
    "programmatic",
    "placeholder",
)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON: {path}: {exc}") from exc


def prompt_files(project: Path) -> set[str] | None:
    prompt_path = project / "image_prompts.json"
    if not prompt_path.is_file():
        return None
    data = load_json(prompt_path)
    prompt_specs = data if isinstance(data, list) else data.get("prompts")
    if not isinstance(prompt_specs, list):
        raise SystemExit(f"image_prompts.json must define a prompts list: {prompt_path}")
    files: set[str] = set()
    for position, spec in enumerate(prompt_specs, start=1):
        if not isinstance(spec, dict) or not isinstance(spec.get("file"), str):
            raise SystemExit(f"image prompt {position} must define file")
        image = spec["file"].replace("\\", "/")
        if image.startswith("/") or ".." in Path(image).parts:
            raise SystemExit(f"image prompt {position} has unsafe file path: {spec['file']}")
        files.add(image)
    return files


def scene_allows_background_reuse(scene: dict, cue: dict) -> bool:
    return bool(scene.get("allowBackgroundReuse") or cue.get("reuse"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a case-video project contract.")
    parser.add_argument("project", type=Path)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"project directory not found: {project}")

    narration = project / "narration.txt"
    if not narration.is_file() or not narration.read_text(encoding="utf-8").strip():
        raise SystemExit(f"missing or empty narration: {narration}")

    timeline = load_json(project / "narration.timeline.json")
    storyboard = load_json(project / "rich_storyboard.json")

    units = timeline.get("units")
    if not isinstance(units, list) or not units:
        raise SystemExit("timeline.units must be a non-empty list")

    indices = [unit.get("index") for unit in units]
    expected_indices = list(range(1, len(units) + 1))
    if indices != expected_indices:
        raise SystemExit(f"timeline unit indices must be continuous 1..{len(units)}")

    scenes = storyboard.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise SystemExit("storyboard.scenes must be a non-empty list")

    covered: list[int] = []
    for position, scene in enumerate(scenes, start=1):
        bounds = scene.get("units")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise SystemExit(f"scene {position} must define units: [first, last]")
        first, last = bounds
        if not isinstance(first, int) or not isinstance(last, int) or first > last:
            raise SystemExit(f"scene {position} has invalid unit bounds: {bounds}")
        covered.extend(range(first, last + 1))

    if covered != expected_indices:
        raise SystemExit(
            "storyboard scene units must be ordered, non-overlapping, and cover "
            f"1..{len(units)}"
        )

    prompt_file_set = prompt_files(project)
    background_count = 0
    scene_primary_backgrounds: list[tuple[int, str, bool]] = []
    for position, scene in enumerate(scenes, start=1):
        backgrounds = scene.get("backgrounds")
        if not isinstance(backgrounds, list) or not backgrounds:
            raise SystemExit(f"scene {position} must define non-empty backgrounds")
        for cue_position, cue in enumerate(backgrounds, start=1):
            if not isinstance(cue, dict):
                raise SystemExit(
                    f"scene {position} background {cue_position} must be an object"
                )
            image = cue.get("image")
            video = cue.get("video")
            if bool(image) == bool(video):
                raise SystemExit(
                    f"scene {position} background {cue_position} must define exactly one of image or video"
                )
            asset = image if image else video
            if not isinstance(asset, str) or not asset.strip():
                raise SystemExit(
                    f"scene {position} background {cue_position} asset path must be a string"
                )
            normalized_asset = asset.replace("\\", "/")
            if normalized_asset.startswith("/") or ".." in Path(normalized_asset).parts:
                raise SystemExit(
                    f"scene {position} background {cue_position} has unsafe asset path: {asset}"
                )
            lower_image = normalized_asset.lower()
            forbidden = next(
                (marker for marker in FORBIDDEN_BACKGROUND_MARKERS if marker in lower_image),
                None,
            )
            if forbidden:
                raise SystemExit(
                    f"scene {position} background {cue_position} uses forbidden final image path "
                    f"{asset!r} matching {forbidden!r}"
                )
            asset_path = project / normalized_asset
            if not asset_path.is_file():
                raise SystemExit(
                    f"scene {position} background {cue_position} asset not found: {asset_path}"
                )
            if image and prompt_file_set is not None and normalized_asset not in prompt_file_set:
                raise SystemExit(
                    f"scene {position} background {cue_position} image is not declared "
                    f"in image_prompts.json: {asset}"
                )
            if cue_position == 1:
                scene_primary_backgrounds.append(
                    (position, normalized_asset, scene_allows_background_reuse(scene, cue))
                )
            background_count += 1

    if prompt_file_set is not None:
        if len(prompt_file_set) < len(scenes):
            raise SystemExit(
                f"image_prompts.json defines {len(prompt_file_set)} prompt files for "
                f"{len(scenes)} scenes"
            )
        seen: dict[str, int] = {}
        for position, image, allow_reuse in scene_primary_backgrounds:
            previous = seen.get(image)
            if previous is not None and not allow_reuse:
                raise SystemExit(
                    f"scene {position} reuses primary background {image!r} from scene "
                    f"{previous}; mark the scene/cue reuse=true only for an explicit fallback"
                )
            seen.setdefault(image, position)

    audio = storyboard.get("audio", "audio/narration_azure.wav")
    audio_path = project / audio
    if not audio_path.is_file():
        raise SystemExit(f"storyboard audio not found: {audio_path}")

    print(
        f"valid project={project} units={len(units)} scenes={len(scenes)} "
        f"backgrounds={background_count} audio={audio}"
    )


if __name__ == "__main__":
    main()
