#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

FORBIDDEN_BACKGROUND_MARKERS = (
    "images/management_cutout/",
    "programmatic",
    "placeholder",
)

ASSET_TYPES = {"image", "video"}
ASSET_ROLES = {"context", "person", "evidence", "document", "map", "metaphor", "texture"}
ASSET_ORIGINS = {"generated", "curated"}
VISUAL_MODES = {"layout", "editorial", "hybrid"}
BEAT_PURPOSES = {
    "establish",
    "identify",
    "evidence",
    "explain",
    "escalate",
    "consequence",
    "callback",
    "reset",
}
BEAT_COMPOSITIONS = {
    "full-bleed",
    "portrait-left",
    "portrait-right",
    "split",
    "triptych",
    "document-focus",
    "evidence-collage",
}
BEAT_TRANSITIONS = {"cut", "dissolve", "push"}
BEAT_CAMERAS = {"static", "push-in", "pull-out", "pan-left", "pan-right"}
BEAT_TREATMENTS = {"natural", "desaturated", "blueprint", "crisis"}
LAYER_KINDS = {
    "asset",
    "text",
    "tint",
    "counter",
    "bar-compare",
    "network",
    "dialogue",
    "annotate",
}
ANNOTATE_SHAPES = {"ring", "arrow", "underline", "box"}
BAR_TONES = {"good", "bad", "neutral"}
# Layer kinds that carry story information beyond a static caption.
EXPRESSIVE_LAYER_KINDS = {"asset", "counter", "bar-compare", "network", "dialogue", "annotate"}
LAYER_SLOTS = {
    "canvas",
    "left",
    "right",
    "center",
    "inset-left",
    "inset-right",
    "top-left",
    "top-right",
    "bottom",
}
SECOND_TIMING_KEYS = {
    "atsecond",
    "atseconds",
    "startsecond",
    "startseconds",
    "endsecond",
    "endseconds",
    "durationsecond",
    "durationseconds",
    "starttime",
    "endtime",
}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pool_asset_records(project: Path) -> dict[str, dict]:
    manifest_path = project / "asset_pool_usage.json"
    if not manifest_path.is_file():
        return {}
    manifest = load_json(manifest_path)
    if manifest.get("schemaVersion") != 1:
        raise SystemExit(f"asset_pool_usage.json has unsupported schemaVersion: {manifest.get('schemaVersion')!r}")
    raw_assets = manifest.get("assets")
    if not isinstance(raw_assets, list):
        raise SystemExit("asset_pool_usage.json must define an assets list")
    records: dict[str, dict] = {}
    asset_ids: set[str] = set()
    for position, record in enumerate(raw_assets, start=1):
        label = f"asset pool record {position}"
        if not isinstance(record, dict):
            raise SystemExit(f"{label} must be an object")
        asset_id = record.get("assetId")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise SystemExit(f"{label} must define a non-empty assetId")
        if asset_id in asset_ids:
            raise SystemExit(f"duplicate asset pool assetId: {asset_id}")
        asset_ids.add(asset_id)
        normalized, local_path = normalized_local_asset(project, record.get("src"), label)
        if normalized in records:
            raise SystemExit(f"duplicate asset pool src: {normalized}")
        expected_hash = record.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise SystemExit(f"{label} must define a lowercase SHA-256 hash")
        actual_hash = sha256_file(local_path)
        if actual_hash != expected_hash:
            raise SystemExit(
                f"{label} hash mismatch for {normalized}: expected {expected_hash}, got {actual_hash}"
            )
        pool_path = record.get("poolPath")
        if not isinstance(pool_path, str) or not pool_path.strip():
            raise SystemExit(f"{label} must define poolPath")
        normalized_pool_path = pool_path.replace("\\", "/")
        if normalized_pool_path.startswith("/") or ".." in Path(normalized_pool_path).parts:
            raise SystemExit(f"{label} has unsafe poolPath: {pool_path}")
        records[normalized] = record
    return records


def scene_allows_background_reuse(scene: dict, cue: dict) -> bool:
    return bool(scene.get("allowBackgroundReuse") or cue.get("reuse"))


def normalized_local_asset(project: Path, asset: object, label: str) -> tuple[str, Path]:
    if not isinstance(asset, str) or not asset.strip():
        raise SystemExit(f"{label} asset path must be a non-empty string")
    normalized = asset.replace("\\", "/")
    if normalized.startswith("/") or ".." in Path(normalized).parts:
        raise SystemExit(f"{label} has unsafe asset path: {asset}")
    path = project / normalized
    if not path.is_file():
        raise SystemExit(f"{label} asset not found: {path}")
    return normalized, path


def reject_second_timing(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in SECOND_TIMING_KEYS or "second" in normalized:
                raise SystemExit(f"{label} uses forbidden second-based timing field: {key}")
            reject_second_timing(child, label)
    elif isinstance(value, list):
        for child in value:
            reject_second_timing(child, label)


def validate_visual_assets(
    project: Path,
    storyboard: dict,
    prompt_file_set: set[str] | None,
    pool_assets: dict[str, dict],
) -> dict[str, dict]:
    raw_assets = storyboard.get("visualAssets")
    if raw_assets is None:
        return {}
    if not isinstance(raw_assets, list):
        raise SystemExit("storyboard.visualAssets must be a list")

    assets: dict[str, dict] = {}
    for position, asset in enumerate(raw_assets, start=1):
        label = f"visual asset {position}"
        if not isinstance(asset, dict):
            raise SystemExit(f"{label} must be an object")
        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise SystemExit(f"{label} must define a non-empty id")
        if asset_id in assets:
            raise SystemExit(f"duplicate visual asset id: {asset_id}")
        asset_type = asset.get("type")
        if asset_type not in ASSET_TYPES:
            raise SystemExit(f"{label} has invalid type: {asset_type!r}")
        role = asset.get("role")
        if role not in ASSET_ROLES:
            raise SystemExit(f"{label} has invalid role: {role!r}")
        origin = asset.get("origin")
        if origin not in ASSET_ORIGINS:
            raise SystemExit(f"{label} has invalid origin: {origin!r}")
        normalized, _ = normalized_local_asset(project, asset.get("src"), label)
        pool_asset_id = asset.get("poolAssetId")
        if pool_asset_id is not None:
            if not isinstance(pool_asset_id, str) or not pool_asset_id.strip():
                raise SystemExit(f"{label} poolAssetId must be a non-empty string")
            if origin != "curated":
                raise SystemExit(f"{label} with poolAssetId must use origin='curated'")
            pool_record = pool_assets.get(normalized)
            if pool_record is None:
                raise SystemExit(
                    f"{label} poolAssetId is not backed by asset_pool_usage.json: {normalized}"
                )
            if pool_record.get("assetId") != pool_asset_id:
                raise SystemExit(
                    f"{label} poolAssetId {pool_asset_id!r} does not match provenance record "
                    f"{pool_record.get('assetId')!r}"
                )
        if asset_type == "image":
            lower_image = normalized.lower()
            forbidden = next(
                (marker for marker in FORBIDDEN_BACKGROUND_MARKERS if marker in lower_image),
                None,
            )
            if forbidden:
                raise SystemExit(
                    f"{label} uses forbidden final image path {normalized!r} matching {forbidden!r}"
                )
            if origin == "generated" and (
                prompt_file_set is None or normalized not in prompt_file_set
            ):
                raise SystemExit(
                    f"{label} generated image is not declared in image_prompts.json: {normalized}"
                )
        assets[asset_id] = asset
    return assets


def unit_start_seconds(unit_by_index: dict[int, dict], index: int) -> float:
    return float(unit_by_index[index]["start"])


def scene_end_seconds(unit_by_index: dict[int, dict], last: int) -> float:
    return float(unit_by_index[last]["end"])


def validate_visual_beats(
    scenes: list[dict],
    assets: dict[str, dict],
    unit_by_index: dict[int, dict],
    warning_seconds: float,
) -> tuple[int, list[str]]:
    beat_ids: set[str] = set()
    beat_count = 0
    warnings: list[str] = []

    for scene_position, scene in enumerate(scenes, start=1):
        first, last = scene["units"]
        mode = scene.get("visualMode", "layout")
        if mode not in VISUAL_MODES:
            raise SystemExit(f"scene {scene_position} has invalid visualMode: {mode!r}")
        raw_beats = scene.get("visualBeats")
        if raw_beats is None:
            continue
        if not isinstance(raw_beats, list) or not raw_beats:
            raise SystemExit(f"scene {scene_position} visualBeats must be a non-empty list")
        reject_second_timing(raw_beats, f"scene {scene_position} visualBeats")

        previous_unit: int | None = None
        previous_asset: str | None = None
        purposes: set[str] = set()
        compositions: set[str] = set()
        for beat_position, beat in enumerate(raw_beats, start=1):
            label = f"scene {scene_position} visual beat {beat_position}"
            if not isinstance(beat, dict):
                raise SystemExit(f"{label} must be an object")
            beat_id = beat.get("id")
            if not isinstance(beat_id, str) or not beat_id.strip():
                raise SystemExit(f"{label} must define a non-empty id")
            if beat_id in beat_ids:
                raise SystemExit(f"duplicate visual beat id: {beat_id}")
            beat_ids.add(beat_id)
            at_unit = beat.get("atUnit")
            if not isinstance(at_unit, int) or at_unit < first or at_unit > last:
                raise SystemExit(
                    f"{label} atUnit must be inside scene units [{first}, {last}]"
                )
            if previous_unit is not None and at_unit <= previous_unit:
                raise SystemExit(f"{label} atUnit must be strictly increasing")
            if beat_position == 1 and mode in {"editorial", "hybrid"} and at_unit != first:
                raise SystemExit(
                    f"scene {scene_position} {mode} mode must begin a visual beat at unit {first}"
                )
            purpose = beat.get("purpose")
            composition = beat.get("composition")
            if purpose not in BEAT_PURPOSES:
                raise SystemExit(f"{label} has invalid purpose: {purpose!r}")
            if composition not in BEAT_COMPOSITIONS:
                raise SystemExit(f"{label} has invalid composition: {composition!r}")
            if beat.get("transition", "cut") not in BEAT_TRANSITIONS:
                raise SystemExit(f"{label} has invalid transition: {beat.get('transition')!r}")
            if beat.get("camera", "static") not in BEAT_CAMERAS:
                raise SystemExit(f"{label} has invalid camera: {beat.get('camera')!r}")
            if beat.get("treatment", "natural") not in BEAT_TREATMENTS:
                raise SystemExit(f"{label} has invalid treatment: {beat.get('treatment')!r}")

            base_asset = beat.get("baseAsset")
            if base_asset is not None and base_asset not in assets:
                raise SystemExit(f"{label} references unknown baseAsset: {base_asset!r}")
            raw_layers = beat.get("layers", [])
            if not isinstance(raw_layers, list):
                raise SystemExit(f"{label} layers must be a list")
            layer_ids: set[str] = set()
            has_asset_layer = False
            for layer_position, layer in enumerate(raw_layers, start=1):
                layer_label = f"{label} layer {layer_position}"
                if not isinstance(layer, dict):
                    raise SystemExit(f"{layer_label} must be an object")
                layer_id = layer.get("id")
                if layer_id is not None:
                    if not isinstance(layer_id, str) or not layer_id.strip():
                        raise SystemExit(f"{layer_label} id must be a non-empty string")
                    if layer_id in layer_ids:
                        raise SystemExit(f"{label} has duplicate layer id: {layer_id}")
                    layer_ids.add(layer_id)
                kind = layer.get("kind")
                slot = layer.get("slot", "canvas")
                if kind not in LAYER_KINDS:
                    raise SystemExit(f"{layer_label} has invalid kind: {kind!r}")
                if slot not in LAYER_SLOTS:
                    raise SystemExit(f"{layer_label} has invalid slot: {slot!r}")
                if kind == "asset":
                    layer_asset = layer.get("asset")
                    if layer_asset not in assets:
                        raise SystemExit(
                            f"{layer_label} references unknown asset: {layer_asset!r}"
                        )
                    has_asset_layer = True
                elif kind == "text":
                    if not isinstance(layer.get("text"), str) or not layer["text"].strip():
                        raise SystemExit(f"{layer_label} text layer must define non-empty text")
                elif kind == "tint":
                    if not isinstance(layer.get("color"), str) or not layer["color"].strip():
                        raise SystemExit(f"{layer_label} tint layer must define color")
                    opacity = layer.get("opacity", 0.25)
                    if not isinstance(opacity, (int, float)) or opacity < 0 or opacity > 1:
                        raise SystemExit(f"{layer_label} tint opacity must be between 0 and 1")
                elif kind == "counter":
                    value = layer.get("value")
                    if not isinstance(value, dict) or not isinstance(value.get("to"), (int, float)):
                        raise SystemExit(f"{layer_label} counter layer must define value.to")
                    if "from" in value and not isinstance(value["from"], (int, float)):
                        raise SystemExit(f"{layer_label} counter value.from must be a number")
                    if layer.get("deltaTone") is not None and layer["deltaTone"] not in BAR_TONES:
                        raise SystemExit(f"{layer_label} has invalid deltaTone: {layer['deltaTone']!r}")
                elif kind == "bar-compare":
                    bars = layer.get("bars")
                    if not isinstance(bars, list) or not bars:
                        raise SystemExit(f"{layer_label} bar-compare layer must define non-empty bars")
                    for bar_position, bar in enumerate(bars, start=1):
                        bar_label = f"{layer_label} bar {bar_position}"
                        if not isinstance(bar, dict):
                            raise SystemExit(f"{bar_label} must be an object")
                        if not isinstance(bar.get("label"), str) or not bar["label"].strip():
                            raise SystemExit(f"{bar_label} must define label")
                        if not isinstance(bar.get("value"), (int, float)):
                            raise SystemExit(f"{bar_label} must define numeric value")
                        if bar.get("tone") is not None and bar["tone"] not in BAR_TONES:
                            raise SystemExit(f"{bar_label} has invalid tone: {bar['tone']!r}")
                elif kind == "network":
                    nodes = layer.get("nodes")
                    if not isinstance(nodes, list) or len(nodes) < 2:
                        raise SystemExit(f"{layer_label} network layer must define at least 2 nodes")
                    node_ids: set[str] = set()
                    for node_position, node in enumerate(nodes, start=1):
                        node_label = f"{layer_label} node {node_position}"
                        if not isinstance(node, dict):
                            raise SystemExit(f"{node_label} must be an object")
                        node_id = node.get("id")
                        if not isinstance(node_id, str) or not node_id.strip():
                            raise SystemExit(f"{node_label} must define id")
                        if node_id in node_ids:
                            raise SystemExit(f"{layer_label} has duplicate node id: {node_id}")
                        node_ids.add(node_id)
                        if not isinstance(node.get("label"), str) or not node["label"].strip():
                            raise SystemExit(f"{node_label} must define label")
                        if node.get("asset") is not None and node["asset"] not in assets:
                            raise SystemExit(f"{node_label} references unknown asset: {node['asset']!r}")
                    links = layer.get("links", [])
                    if not isinstance(links, list):
                        raise SystemExit(f"{layer_label} links must be a list")
                    for link_position, link in enumerate(links, start=1):
                        link_label = f"{layer_label} link {link_position}"
                        if not isinstance(link, dict):
                            raise SystemExit(f"{link_label} must be an object")
                        if link.get("from") not in node_ids or link.get("to") not in node_ids:
                            raise SystemExit(f"{link_label} must reference declared node ids")
                elif kind == "dialogue":
                    if not isinstance(layer.get("text"), str) or not layer["text"].strip():
                        raise SystemExit(f"{layer_label} dialogue layer must define non-empty text")
                    if not isinstance(layer.get("speaker"), str) or not layer["speaker"].strip():
                        raise SystemExit(f"{layer_label} dialogue layer must define speaker")
                    if layer.get("tail") is not None and layer["tail"] not in {"left", "right"}:
                        raise SystemExit(f"{layer_label} has invalid tail: {layer['tail']!r}")
                elif kind == "annotate":
                    region = layer.get("region")
                    if not isinstance(region, dict):
                        raise SystemExit(f"{layer_label} annotate layer must define region")
                    for axis in ("x", "y", "w", "h"):
                        coord = region.get(axis)
                        if not isinstance(coord, (int, float)) or coord < 0 or coord > 1:
                            raise SystemExit(
                                f"{layer_label} region.{axis} must be a number between 0 and 1"
                            )
                    if layer.get("shape") is not None and layer["shape"] not in ANNOTATE_SHAPES:
                        raise SystemExit(f"{layer_label} has invalid shape: {layer['shape']!r}")

                reveal = layer.get("revealAtUnit", at_unit)
                exit_unit = layer.get("exitAtUnit")
                if not isinstance(reveal, int) or reveal < at_unit or reveal > last:
                    raise SystemExit(
                        f"{layer_label} revealAtUnit must be between beat unit {at_unit} and scene unit {last}"
                    )
                if exit_unit is not None and (
                    not isinstance(exit_unit, int) or exit_unit <= reveal or exit_unit > last
                ):
                    raise SystemExit(
                        f"{layer_label} exitAtUnit must be after revealAtUnit and inside the scene"
                    )

            if base_asset is None and not has_asset_layer:
                raise SystemExit(f"{label} must define baseAsset or at least one asset layer")

            if previous_asset == base_asset and purpose != "callback":
                warnings.append(
                    f"scene {scene_position} beats {beat_position - 1}-{beat_position} repeat "
                    f"baseAsset {base_asset!r} without callback purpose"
                )
            previous_unit = at_unit
            previous_asset = base_asset
            purposes.add(purpose)
            compositions.add(composition)
            beat_count += 1

        for beat_position, beat in enumerate(raw_beats, start=1):
            start = unit_start_seconds(unit_by_index, beat["atUnit"])
            if beat_position < len(raw_beats):
                end = unit_start_seconds(unit_by_index, raw_beats[beat_position]["atUnit"])
            else:
                end = scene_end_seconds(unit_by_index, last)
            if end - start > warning_seconds:
                warnings.append(
                    f"scene {scene_position} visual beat {beat_position} lasts {end - start:.1f}s; "
                    "review whether a semantic change deserves another beat"
                )
            # Expressiveness: a long beat with no internal reveal plays as a
            # frozen slide regardless of how good the base image is.
            if end - start > 8.0:
                beat_unit = beat["atUnit"]
                has_internal_reveal = any(
                    isinstance(layer, dict) and layer.get("revealAtUnit", beat_unit) > beat_unit
                    for layer in beat.get("layers", [])
                )
                if not has_internal_reveal:
                    warnings.append(
                        f"scene {scene_position} visual beat {beat_position} lasts {end - start:.1f}s "
                        "with no internal layer reveal; add staged reveals or split the beat"
                    )
        if len(raw_beats) >= 3 and len(purposes) == 1:
            warnings.append(f"scene {scene_position} uses one purpose across {len(raw_beats)} beats")
        if len(raw_beats) >= 3 and len(compositions) == 1:
            warnings.append(
                f"scene {scene_position} uses one composition across {len(raw_beats)} beats"
            )
        # Expressiveness: three consecutive beats of caption-only layers mean the
        # visuals are narrating with static text instead of acting.
        text_only_run = 0
        for beat in raw_beats:
            kinds = {
                layer.get("kind")
                for layer in beat.get("layers", [])
                if isinstance(layer, dict)
            }
            if kinds and not (kinds & EXPRESSIVE_LAYER_KINDS):
                text_only_run += 1
                if text_only_run == 3:
                    warnings.append(
                        f"scene {scene_position} has 3+ consecutive beats with text/tint layers only; "
                        "use counter, bar-compare, network, dialogue, annotate, or asset layers"
                    )
            else:
                text_only_run = 0

    return beat_count, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a case-video project contract.")
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--visual-warning-seconds",
        type=float,
        default=12.0,
        help="Warn when one Visual Beat exceeds this duration; does not fail validation.",
    )
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
    unit_by_index = {int(unit["index"]): unit for unit in units}

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
    pool_assets = pool_asset_records(project)
    visual_assets = validate_visual_assets(project, storyboard, prompt_file_set, pool_assets)
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
            normalized_asset, asset_path = normalized_local_asset(
                project,
                asset,
                f"scene {position} background {cue_position}",
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
            if (
                image
                and prompt_file_set is not None
                and normalized_asset not in prompt_file_set
                and normalized_asset not in pool_assets
            ):
                raise SystemExit(
                    f"scene {position} background {cue_position} image is not declared "
                    f"in image_prompts.json or asset_pool_usage.json: {asset}"
                )
            if cue_position == 1:
                scene_primary_backgrounds.append(
                    (position, normalized_asset, scene_allows_background_reuse(scene, cue))
                )
            background_count += 1

    if prompt_file_set is not None:
        declared_images = prompt_file_set | set(pool_assets)
        if not visual_assets and len(declared_images) < len(scenes):
            raise SystemExit(
                f"image_prompts.json and asset_pool_usage.json declare "
                f"{len(declared_images)} image files for "
                f"{len(scenes)} scenes"
            )
        seen: dict[str, int] = {}
        for position, image, allow_reuse in scene_primary_backgrounds:
            previous = seen.get(image)
            if previous is not None and not allow_reuse:
                raise SystemExit(
                    f"scene {position} reuses primary background {image!r} from scene "
                    f"{previous}; mark the scene/cue reuse=true for an intentional callback "
                    "or repeated visual motif"
                )
            seen.setdefault(image, position)

    visual_beat_count, visual_warnings = validate_visual_beats(
        scenes,
        visual_assets,
        unit_by_index,
        args.visual_warning_seconds,
    )

    audio = storyboard.get("audio", "audio/narration_azure.wav")
    audio_path = project / audio
    if not audio_path.is_file():
        raise SystemExit(f"storyboard audio not found: {audio_path}")

    for warning in visual_warnings:
        print(f"warning: {warning}")

    print(
        f"valid project={project} units={len(units)} scenes={len(scenes)} "
        f"backgrounds={background_count} visualAssets={len(visual_assets)} "
        f"poolAssets={len(pool_assets)} visualBeats={visual_beat_count} "
        f"warnings={len(visual_warnings)} audio={audio}"
    )


if __name__ == "__main__":
    main()
