#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from PIL import Image, UnidentifiedImageError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.app.services.visual_adapter import prompt_image_path

FORBIDDEN_BACKGROUND_MARKERS = (
    "images/management_cutout/",
    "programmatic",
    "placeholder",
)
FORBIDDEN_FINAL_IMAGE_DIR_PARTS = {
    "qa",
    "contact-sheet",
    "contact-sheets",
    "contact_sheet",
    "contact_sheets",
}
FORBIDDEN_FINAL_IMAGE_NAME_MARKERS = (
    "contact-sheet",
    "contact_sheet",
    "overview",
    "thumbnail",
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

ASSET_TYPES = {"image", "video"}
ASSET_ROLES = {"context", "person", "evidence", "document", "map", "metaphor", "texture"}
ASSET_ORIGINS = {"generated", "curated"}
BACKGROUND_TRANSITIONS = {"wash", "paper", "ink", "flash", "push"}
BACKGROUND_MOTIONS = {"center", "left", "right", "lift", "drift", "breathe"}
VISUAL_MODES = {"layout", "editorial", "hybrid"}
VISUAL_INTENTS = {
    "context",
    "protagonist",
    "claim",
    "evidence",
    "relationship",
    "mechanism",
    "decision",
    "consequence",
    "reflection",
}
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
BEAT_CAMERAS = {"static", "push-in", "pull-out", "pan-left", "pan-right", "drift", "breathe"}
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
ANNOTATE_SHAPES = {"arrow", "underline"}
DISABLED_ANNOTATE_SHAPES = {"box", "ring"}
BAR_TONES = {"good", "bad", "neutral"}
# Layer kinds that carry story information beyond a static caption.
EXPRESSIVE_LAYER_KINDS = {"asset", "counter", "bar-compare", "network", "dialogue", "annotate"}
PANEL_LAYER_KINDS = {"text", "counter", "bar-compare", "network", "dialogue"}
HYBRID_ALLOWED_LAYER_KINDS = {"tint"}
MAX_BAR_ITEMS = 4
MAX_NETWORK_NODES = 4
NETWORK_LAYOUTS = {"auto", "row", "column", "triangle", "hub", "grid"}
CANVAS_TONES = {"transparent", "light", "dark"}
OPAQUE_TEXT_SURFACES = {"paper", "solid", "accent"}
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


def load_authored_title(project: Path) -> str | None:
    path = project / "title.txt"
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise SystemExit("title.txt must contain exactly one non-empty logical line")
    return lines[0].strip()


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
        if not isinstance(spec, dict):
            raise SystemExit(f"image prompt {position} must be an object")
        image = prompt_image_path(spec)
        if not image:
            raise SystemExit(f"image prompt {position} must define a safe file or scene_id")
        if image.startswith("/") or ".." in Path(image).parts:
            raise SystemExit(f"image prompt {position} has unsafe file path: {image}")
        validate_final_image_path(image, f"image prompt {position}")
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


def count_true_runs(values: list[bool], *, min_length: int) -> int:
    runs = 0
    current = 0
    for value in values:
        if value:
            current += 1
            continue
        if current >= min_length:
            runs += 1
        current = 0
    if current >= min_length:
        runs += 1
    return runs


def looks_like_contact_sheet_or_overview(image: Image.Image) -> bool:
    width, height = image.size
    if width < 900 or height < 700:
        return False
    # Symmetric window: catch grid sheets in both landscape and portrait
    # orientation while letting native 16:9 / 9:16 backgrounds through.
    ratio = max(width, height) / min(width, height)
    if ratio > 1.45:
        return False

    sample_width = 320
    sample_height = max(1, round(height * sample_width / width))
    sample = image.convert("RGB").resize((sample_width, sample_height))
    light_pixels: list[bool] = []
    for red, green, blue in sample.getdata():
        light_pixels.append(red >= 238 and green >= 238 and blue >= 238)

    light_fraction = sum(light_pixels) / len(light_pixels)
    if light_fraction < 0.25:
        return False

    rows: list[bool] = []
    for y in range(sample_height):
        offset = y * sample_width
        row_light = sum(light_pixels[offset:offset + sample_width]) / sample_width
        rows.append(row_light >= 0.80)

    columns: list[bool] = []
    for x in range(sample_width):
        column_light = sum(light_pixels[y * sample_width + x] for y in range(sample_height))
        columns.append(column_light / sample_height >= 0.80)

    min_row_run = max(2, round(sample_height * 0.006))
    min_column_run = max(2, round(sample_width * 0.006))
    row_runs = count_true_runs(rows, min_length=min_row_run)
    column_runs = count_true_runs(columns, min_length=min_column_run)
    return row_runs >= 3 and column_runs >= 2


def validate_final_image_path(normalized: str, label: str) -> None:
    lower_image = normalized.lower()
    forbidden = next(
        (marker for marker in FORBIDDEN_BACKGROUND_MARKERS if marker in lower_image),
        None,
    )
    if forbidden:
        raise SystemExit(
            f"{label} uses forbidden final image path {normalized!r} matching {forbidden!r}"
        )
    path = Path(lower_image)
    forbidden_part = next(
        (part for part in path.parts if part in FORBIDDEN_FINAL_IMAGE_DIR_PARTS),
        None,
    )
    if forbidden_part:
        raise SystemExit(
            f"{label} uses forbidden final image path {normalized!r} matching {forbidden_part!r}"
        )
    forbidden_name = next(
        (marker for marker in FORBIDDEN_FINAL_IMAGE_NAME_MARKERS if marker in path.name),
        None,
    )
    if forbidden_name:
        raise SystemExit(
            f"{label} uses forbidden final image path {normalized!r} matching {forbidden_name!r}"
        )


def validate_final_image_asset(
    normalized: str,
    path: Path,
    label: str,
    checked_images: set[str],
) -> None:
    validate_final_image_path(normalized, label)
    if normalized in checked_images:
        return
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise SystemExit(f"{label} image has unsupported file extension: {normalized}")
    try:
        with Image.open(path) as image:
            image.load()
            path_parts = Path(normalized).parts
            is_character_portrait = len(path_parts) >= 2 and path_parts[:2] == (
                "images",
                "characters",
            )
            # Generated FDE portraits are intentionally stored beside other
            # project-local assets under images/generated/. Their pure-white
            # backgrounds can resemble the spacing pattern of a contact sheet
            # to the generic image heuristic, so identify the explicit char-*
            # asset naming convention as portrait evidence too.
            is_character_portrait = is_character_portrait or path.name.startswith(("char-", "portrait-"))
            if not is_character_portrait and looks_like_contact_sheet_or_overview(image):
                raise SystemExit(
                    f"{label} image appears to be a contact sheet/overview QA image, "
                    f"not a final video asset: {normalized}"
                )
    except SystemExit:
        raise
    except (UnidentifiedImageError, OSError) as exc:
        raise SystemExit(f"{label} image is not readable: {normalized}") from exc
    checked_images.add(normalized)


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
    checked_images: set[str],
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
        normalized, asset_path = normalized_local_asset(project, asset.get("src"), label)
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
            validate_final_image_asset(normalized, asset_path, label, checked_images)
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


def semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: semantic_value(child)
            for key, child in sorted(value.items())
            if key not in {"id", "slot", "revealAtUnit", "exitAtUnit"}
        }
    if isinstance(value, list):
        return [semantic_value(item) for item in value]
    return value


def is_rendered_visual_layer(layer: dict[str, Any]) -> bool:
    return (
        layer.get("kind") != "annotate"
        or layer.get("shape") in ANNOTATE_SHAPES
    )


def beat_semantic_signature(beat: dict) -> str:
    payload = {
        "baseAsset": beat.get("baseAsset"),
        "layers": [
            semantic_value(layer)
            for layer in beat.get("layers", [])
            if isinstance(layer, dict) and is_rendered_visual_layer(layer)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def semantic_event_units(raw_beats: list[dict], first: int) -> set[int]:
    events = {first}
    previous_signature: str | None = None
    for beat in raw_beats:
        at_unit = beat["atUnit"]
        signature = beat_semantic_signature(beat)
        if signature != previous_signature:
            events.add(at_unit)
        previous_signature = signature
        for layer in beat.get("layers", []):
            if not isinstance(layer, dict):
                continue
            if not is_rendered_visual_layer(layer):
                continue
            events.add(layer.get("revealAtUnit", at_unit))
            if isinstance(layer.get("exitAtUnit"), int):
                events.add(layer["exitAtUnit"])
            for nested_key in ("bars", "nodes", "links"):
                nested_items = layer.get(nested_key)
                if not isinstance(nested_items, list):
                    continue
                for nested in nested_items:
                    if isinstance(nested, dict):
                        events.add(
                            nested.get(
                                "revealAtUnit",
                                layer.get("revealAtUnit", at_unit),
                            )
                        )
    return events


def visual_quality_issue(
    message: str,
    *,
    strict: bool,
    warnings: list[str],
    errors: list[str],
) -> None:
    (errors if strict else warnings).append(message)


# Text-surface contrast guardrail. The Remotion text surfaces have known
# backgrounds (see textSurfaceStyle in VisualBeatTrack.tsx): glass/solid and the
# legacy default card are dark navy, paper is light cream and accent is the
# palette yellow. A declared text color must stay legible on its surface.
TEXT_SURFACE_BACKGROUNDS = {
    "glass": ((5, 17, 31), 0.68),
    "solid": ((5, 17, 31), 0.92),
    "paper": ((246, 239, 218), 0.96),
    "accent": ((255, 212, 90), 1.0),
}
LEGACY_TEXT_SURFACE_BACKGROUND = ((5, 17, 31), 0.9)
MIN_TEXT_SURFACE_CONTRAST = 3.0
PERSON_PANEL_MIN_GAP = 0.012
COUNTER_MIN_FONT_SIZE = 42.0


def normalized_layer_box(
    layer: dict[str, Any], label: str
) -> tuple[float, float, float, float] | None:
    raw_box = layer.get("box")
    if raw_box is None:
        return None
    if not isinstance(raw_box, dict):
        raise SystemExit(f"{label} box must be an object")

    x = raw_box.get("x")
    y = raw_box.get("y")
    width = raw_box.get("width", raw_box.get("w"))
    height = raw_box.get("height", raw_box.get("h"))
    values = {"x": x, "y": y, "width": width, "height": height}
    for axis, value in values.items():
        if not isinstance(value, (int, float)) or value < 0 or value > 1:
            raise SystemExit(
                f"{label} box.{axis} must be a number between 0 and 1"
            )
    if width <= 0 or height <= 0:
        raise SystemExit(f"{label} box width and height must be greater than 0")
    if x + width > 1:
        raise SystemExit(f"{label} box exceeds the right canvas edge")
    if y + height > 1:
        raise SystemExit(f"{label} box exceeds the bottom canvas edge")
    return float(x), float(y), float(width), float(height)


def layer_boxes_conflict(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    *,
    gap: float = PERSON_PANEL_MIN_GAP,
) -> bool:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    horizontally_separated = (
        first_x + first_width + gap <= second_x
        or second_x + second_width + gap <= first_x
    )
    vertically_separated = (
        first_y + first_height + gap <= second_y
        or second_y + second_height + gap <= first_y
    )
    return not (horizontally_separated or vertically_separated)


def estimated_counter_text_units(text: str) -> float:
    units = 0.0
    for character in text:
        if character.isspace():
            units += 0.34
        elif "\u2e80" <= character <= "\u9fff" or "\uf900" <= character <= "\ufaff":
            units += 1.0
        elif character.isupper() or character.isdigit():
            units += 0.66
        elif character.islower():
            units += 0.56
        else:
            units += 0.48
    return max(1.0, units)


def counter_fitted_font_size(
    layer: dict[str, Any],
    box: tuple[float, float, float, float],
    canvas_width: int,
) -> float:
    value = layer["value"]
    decimals = int(value.get("decimals", 0))
    prefix = str(value.get("prefix", ""))
    suffix = str(value.get("suffix", ""))
    final_text = f"{prefix}{value['to']:.{decimals}f}{suffix}"
    width_pixels = box[2] * canvas_width
    horizontal_padding = min(44.0, max(20.0, width_pixels * 0.08))
    inner_width = max(96.0, width_pixels - horizontal_padding * 2 - 10.0)
    legacy_delta = "from" in value and value.get("from") != 0
    show_delta = layer.get("showDelta", legacy_delta)
    if not show_delta:
        return inner_width * 0.84 / estimated_counter_text_units(final_text)
    delta = abs(value["to"] - value["from"])
    delta_text = f"{delta:.{decimals}f}{suffix}"
    combined_units = estimated_counter_text_units(final_text) + (
        estimated_counter_text_units(delta_text) + 1.15
    ) * 0.38
    return (inner_width * 0.84 - 18.0) / max(1.0, combined_units)

# Frame-0 cover splash cap, mirrored from engine/remotion/src/canvas.ts
# (COVER_MAX_SECONDS). The engine clamps the cover to this window; plans that
# author a longer hold through cover.throughUnit get a contract warning.
COVER_SPLASH_MAX_SECONDS = 2.0


def hex_text_color(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"#([0-9a-fA-F]{6})", value.strip())
    if not match:
        return None
    raw = match.group(1)
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def srgb_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        c = value / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(component) for component in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_surface_contrast(layer: dict) -> float | None:
    """Contrast ratio between a text layer color and its rendered surface."""
    color = hex_text_color(layer.get("color"))
    if color is None:
        return None
    surface = layer.get("surface")
    if surface == "none":
        return None
    background = TEXT_SURFACE_BACKGROUNDS.get(surface) if surface else None
    if background is None:
        background = LEGACY_TEXT_SURFACE_BACKGROUND if surface is None else None
    if background is None:
        return None
    (fg, alpha) = background
    # Composite the translucent surface over the bright cream canvas default.
    base = (246, 239, 218)
    effective = tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, base))
    text_lum = srgb_luminance(color)
    surface_lum = srgb_luminance(effective)
    high, low = max(text_lum, surface_lum), min(text_lum, surface_lum)
    return (high + 0.05) / (low + 0.05)


def is_background_like_asset(asset_id: str | None, asset: dict | None) -> bool:
    text = str(asset_id or "").strip().lower()
    src = str((asset or {}).get("src", "")).strip().lower()
    name = Path(src).name
    stem = Path(src).stem
    markers = ("bg-", "bg_", "background-", "background_")
    suffixes = ("-bg", "_bg", "-background", "_background")
    infixes = ("-bg-", "_bg_", "-background-", "_background_")
    return (
        text.startswith(markers)
        or text.endswith(suffixes)
        or any(marker in text for marker in infixes)
        or name.startswith(markers)
        or name.endswith(suffixes)
        or stem.startswith(markers)
        or stem.endswith(suffixes)
        or any(marker in src for marker in ("/bg-", "/bg_", "\\bg-", "\\bg_"))
        or any(marker in src for marker in infixes)
    )


def validate_visual_beats(
    scenes: list[dict],
    assets: dict[str, dict],
    unit_by_index: dict[int, dict],
    warning_seconds: float,
    max_visual_gap_seconds: float,
    strict_visuals: bool,
    canvas_width: int,
    canvas_height: int,
) -> tuple[int, list[str], list[str]]:
    beat_ids: set[str] = set()
    beat_count = 0
    warnings: list[str] = []
    errors: list[str] = []

    for scene_position, scene in enumerate(scenes, start=1):
        first, last = scene["units"]
        raw_beats = scene.get("visualBeats")
        mode = scene.get(
            "visualMode",
            "editorial" if isinstance(raw_beats, list) and raw_beats else "layout",
        )
        if mode not in VISUAL_MODES:
            raise SystemExit(f"scene {scene_position} has invalid visualMode: {mode!r}")
        if raw_beats is None:
            continue
        if not isinstance(raw_beats, list) or not raw_beats:
            raise SystemExit(f"scene {scene_position} visualBeats must be a non-empty list")
        reject_second_timing(raw_beats, f"scene {scene_position} visualBeats")

        previous_unit: int | None = None
        previous_asset: str | None = None
        previous_signature: str | None = None
        purposes: set[str] = set()
        compositions: set[str] = set()
        callback_count = 0
        hybrid_semantic_kinds: set[str] = set()
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
            visual_intent = beat.get("visualIntent")
            if visual_intent is not None and visual_intent not in VISUAL_INTENTS:
                raise SystemExit(f"{label} has invalid visualIntent: {visual_intent!r}")
            if purpose not in BEAT_PURPOSES:
                raise SystemExit(f"{label} has invalid purpose: {purpose!r}")
            if purpose == "callback":
                callback_count += 1
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
            raw_render = beat.get("render")
            if raw_render is not None:
                if not isinstance(raw_render, dict):
                    raise SystemExit(f"{label} render must be an object")
                canvas_tone = raw_render.get("canvasTone")
                if canvas_tone is not None and canvas_tone not in CANVAS_TONES:
                    raise SystemExit(f"{label} has invalid render.canvasTone: {canvas_tone!r}")
                if is_background_like_asset(base_asset, assets.get(base_asset)) and canvas_tone != "transparent":
                    visual_quality_issue(
                        f"{label} uses background-like baseAsset {base_asset!r} with opaque "
                        f"render.canvasTone {canvas_tone!r}; keep the generated background "
                        "visible with canvasTone 'transparent' and use tint, overlay, or "
                        "bounded text layers for readability",
                        strict=strict_visuals,
                        warnings=warnings,
                        errors=errors,
                    )
                if base_asset is not None:
                    treatment_color = raw_render.get("treatmentColor")
                    if isinstance(treatment_color, str):
                        color_value = treatment_color.strip().lstrip("#")
                        if len(color_value) == 6 or (
                            len(color_value) == 8 and color_value[6:].lower() == "ff"
                        ):
                            visual_quality_issue(
                                f"{label} treatmentColor {treatment_color!r} is opaque and "
                                "hides the base asset; use 'transparent' or an 8-digit "
                                "#RRGGBBAA value with a non-opaque alpha channel",
                                strict=strict_visuals,
                                warnings=warnings,
                                errors=errors,
                            )
            raw_layers = beat.get("layers", [])
            if not isinstance(raw_layers, list):
                raise SystemExit(f"{label} layers must be a list")
            layer_ids: set[str] = set()
            has_asset_layer = False
            panel_layers: list[
                tuple[
                    str,
                    str,
                    int,
                    int,
                    str,
                    tuple[float, float, float, float] | None,
                ]
            ] = []
            person_layers: list[
                tuple[int, int, str, tuple[float, float, float, float]]
            ] = []
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
                layer_box = normalized_layer_box(layer, layer_label)
                is_person_asset = False
                if (
                    mode == "hybrid"
                    and kind not in HYBRID_ALLOWED_LAYER_KINDS
                    and is_rendered_visual_layer(layer)
                ):
                    hybrid_semantic_kinds.add(kind)
                if kind == "asset":
                    layer_asset = layer.get("asset")
                    if layer_asset not in assets:
                        raise SystemExit(
                            f"{layer_label} references unknown asset: {layer_asset!r}"
                        )
                    is_person_asset = assets[layer_asset].get("role") == "person"
                    if is_person_asset and layer_box is None:
                        visual_quality_issue(
                            f"{layer_label} renders person asset {layer_asset!r} without an "
                            "explicit box; the director must reserve the portrait region while "
                            "Remotion owns deterministic square framing and contain-fit",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )
                    has_asset_layer = True
                elif kind == "text":
                    if not isinstance(layer.get("text"), str) or not layer["text"].strip():
                        raise SystemExit(f"{layer_label} text layer must define non-empty text")
                    if layer.get("surface") in OPAQUE_TEXT_SURFACES and layer.get("box") is None:
                        visual_quality_issue(
                            f"{layer_label} uses {layer.get('surface')!r} surface without an explicit "
                            "box; use compact glass/none text on a slot or bind opaque card "
                            "surfaces to a declared box so they cannot cover the background",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )
                    contrast = text_surface_contrast(layer)
                    if contrast is not None and contrast < MIN_TEXT_SURFACE_CONTRAST:
                        visual_quality_issue(
                            f"{layer_label} text color {layer.get('color')!r} on "
                            f"{layer.get('surface') or 'legacy dark'} surface has contrast "
                            f"{contrast:.2f} (< {MIN_TEXT_SURFACE_CONTRAST}); use light text "
                            "(e.g. #F7E7C7) on glass/solid/legacy dark surfaces and dark ink "
                            "(e.g. #12325E) on paper/accent surfaces",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )
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
                    show_delta = layer.get("showDelta")
                    if show_delta is not None and not isinstance(show_delta, bool):
                        raise SystemExit(f"{layer_label} counter showDelta must be a boolean")
                    if show_delta is True and "from" not in value:
                        raise SystemExit(
                            f"{layer_label} counter showDelta=true requires value.from so the delta has a baseline"
                        )
                    if show_delta is None and "from" in value and value["from"] != 0:
                        warnings.append(
                            f"{layer_label} relies on legacy implicit delta display from non-zero value.from; "
                            "set showDelta=true explicitly for a comparison or false for count-up only"
                        )
                    if layer.get("deltaTone") is not None and layer["deltaTone"] not in BAR_TONES:
                        raise SystemExit(f"{layer_label} has invalid deltaTone: {layer['deltaTone']!r}")
                    if layer_box is not None:
                        fitted_size = counter_fitted_font_size(layer, layer_box, canvas_width)
                        if fitted_size < COUNTER_MIN_FONT_SIZE:
                            visual_quality_issue(
                                f"{layer_label} counter content cannot fit its declared box at the "
                                f"{COUNTER_MIN_FONT_SIZE:.0f}px readability floor (estimated "
                                f"{fitted_size:.1f}px); widen the box, shorten prefix/suffix, or split the beat",
                                strict=strict_visuals,
                                warnings=warnings,
                                errors=errors,
                            )
                elif kind == "bar-compare":
                    bars = layer.get("bars")
                    if not isinstance(bars, list) or not bars:
                        raise SystemExit(f"{layer_label} bar-compare layer must define non-empty bars")
                    if len(bars) > MAX_BAR_ITEMS:
                        visual_quality_issue(
                            f"{layer_label} defines {len(bars)} bars; use at most {MAX_BAR_ITEMS} "
                            "or split the comparison across beats",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )
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
                    network_layout = layer.get("networkLayout", "auto")
                    if network_layout not in NETWORK_LAYOUTS:
                        raise SystemExit(
                            f"{layer_label} has invalid networkLayout: {network_layout!r}"
                        )
                    if network_layout == "triangle" and len(nodes) != 3:
                        raise SystemExit(
                            f"{layer_label} triangle networkLayout requires exactly 3 nodes"
                        )
                    if network_layout == "hub" and len(nodes) < 3:
                        raise SystemExit(
                            f"{layer_label} hub networkLayout requires at least 3 nodes"
                        )
                    if len(nodes) > MAX_NETWORK_NODES:
                        visual_quality_issue(
                            f"{layer_label} defines {len(nodes)} nodes; use at most "
                            f"{MAX_NETWORK_NODES} or split the network across beats",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )
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
                    if not layer.get("asset"):
                        warnings.append(
                            f"{layer_label} dialogue layer has no 'asset'; "
                            "bind a character portrait ID so the speaker image renders beside the bubble"
                        )
                elif kind == "annotate":
                    shape = layer.get("shape")
                    if shape is None:
                        warnings.append(
                            f"{layer_label} omits annotate shape; the old implicit 'box' "
                            "default is disabled and Remotion skips it. Use arrow, underline, "
                            "or a focused crop."
                        )
                    elif shape in DISABLED_ANNOTATE_SHAPES:
                        warnings.append(
                            f"{layer_label} uses disabled annotate shape {shape!r}; "
                            "Remotion skips it. Replace it with arrow, underline, or a focused crop."
                        )
                    elif shape not in ANNOTATE_SHAPES:
                        raise SystemExit(f"{layer_label} has invalid shape: {shape!r}")
                    else:
                        region = layer.get("region")
                        if not isinstance(region, dict):
                            raise SystemExit(f"{layer_label} annotate layer must define region")
                        for axis in ("x", "y", "w", "h"):
                            coord = region.get(axis)
                            if not isinstance(coord, (int, float)) or coord < 0 or coord > 1:
                                raise SystemExit(
                                    f"{layer_label} region.{axis} must be a number between 0 and 1"
                                )
                        if region["x"] + region["w"] > 1:
                            raise SystemExit(f"{layer_label} region exceeds the right canvas edge")
                        if region["y"] + region["h"] > 1:
                            raise SystemExit(f"{layer_label} region exceeds the bottom canvas edge")

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
                if kind in PANEL_LAYER_KINDS:
                    panel_layers.append(
                        (
                            slot,
                            kind,
                            reveal,
                            exit_unit if exit_unit is not None else last + 1,
                            layer_label,
                            layer_box,
                        )
                    )
                if is_person_asset and layer_box is not None:
                    person_layers.append(
                        (
                            reveal,
                            exit_unit if exit_unit is not None else last + 1,
                            layer_label,
                            layer_box,
                        )
                    )

            for panel_position, panel in enumerate(panel_layers):
                slot, kind, reveal, exit_unit, panel_label, panel_box = panel
                for other in panel_layers[panel_position + 1 :]:
                    (
                        other_slot,
                        other_kind,
                        other_reveal,
                        other_exit,
                        other_label,
                        other_box,
                    ) = other
                    if slot != other_slot:
                        continue
                    if max(reveal, other_reveal) >= min(exit_unit, other_exit):
                        continue
                    if panel_box is not None and other_box is not None:
                        if not layer_boxes_conflict(panel_box, other_box, gap=0):
                            continue
                        detail = "their declared boxes intersect"
                    else:
                        detail = "one or both layers omit an explicit box"
                    visual_quality_issue(
                        f"{panel_label} ({kind}) overlaps {other_label} ({other_kind}) in slot "
                        f"{slot!r}: {detail}; assign non-overlapping boxes, different slots, "
                        "or non-overlapping reveal/exit units",
                        strict=strict_visuals,
                        warnings=warnings,
                        errors=errors,
                    )

            for person_reveal, person_exit, person_label, person_box in person_layers:
                for (
                    _panel_slot,
                    panel_kind,
                    panel_reveal,
                    panel_exit,
                    panel_label,
                    panel_box,
                ) in panel_layers:
                    if max(person_reveal, panel_reveal) >= min(person_exit, panel_exit):
                        continue
                    if panel_box is None:
                        visual_quality_issue(
                            f"{panel_label} ({panel_kind}) shares a beat with {person_label} "
                            "but has no explicit box; reserve both portrait and panel regions "
                            "so their composition is deterministic",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )
                        continue
                    if layer_boxes_conflict(person_box, panel_box):
                        visual_quality_issue(
                            f"{person_label} portrait box overlaps {panel_label} "
                            f"({panel_kind}); reserve non-overlapping boxes with at least "
                            f"{PERSON_PANEL_MIN_GAP:.3f} normalized gap. The director owns "
                            "composition, while Remotion owns square framing and media fit",
                            strict=strict_visuals,
                            warnings=warnings,
                            errors=errors,
                        )

            if base_asset is None and not has_asset_layer:
                raise SystemExit(f"{label} must define baseAsset or at least one asset layer")

            if previous_asset == base_asset and purpose != "callback":
                warnings.append(
                    f"scene {scene_position} beats {beat_position - 1}-{beat_position} repeat "
                    f"baseAsset {base_asset!r} without callback purpose"
                )
            signature = beat_semantic_signature(beat)
            if previous_signature == signature:
                visual_quality_issue(
                    f"scene {scene_position} visual beat {beat_position} introduces no semantic "
                    "change; camera or composition changes alone do not justify another beat",
                    strict=strict_visuals,
                    warnings=warnings,
                    errors=errors,
                )
            previous_unit = at_unit
            previous_asset = base_asset
            previous_signature = signature
            purposes.add(purpose)
            compositions.add(composition)
            beat_count += 1

        if len(raw_beats) >= 3 and callback_count / len(raw_beats) > 0.35:
            visual_quality_issue(
                f"scene {scene_position} uses callback purpose on {callback_count}/"
                f"{len(raw_beats)} beats; callbacks must be occasional, content-motivated returns",
                strict=strict_visuals,
                warnings=warnings,
                errors=errors,
            )
        if hybrid_semantic_kinds:
            visual_quality_issue(
                f"scene {scene_position} hybrid mode contains semantic Visual Beat layers "
                f"{sorted(hybrid_semantic_kinds)}; keep hybrid beats image/tint-only and put "
                "semantic panels in layout props, or use editorial mode",
                strict=strict_visuals,
                warnings=warnings,
                errors=errors,
            )

        event_units = semantic_event_units(raw_beats, first)
        event_times = [unit_start_seconds(unit_by_index, unit) for unit in sorted(event_units)]
        event_times.append(scene_end_seconds(unit_by_index, last))
        max_gap = max(
            (end - start for start, end in zip(event_times, event_times[1:])),
            default=0.0,
        )
        if max_gap > max_visual_gap_seconds:
            visual_quality_issue(
                f"scene {scene_position} has a {max_gap:.1f}s gap without a semantic visual "
                f"change; keep gaps within {max_visual_gap_seconds:.1f}s by adding content-bearing "
                "assets, evidence, or staged semantic reveals",
                strict=strict_visuals,
                warnings=warnings,
                errors=errors,
            )

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
                has_internal_reveal = False
                for layer in beat.get("layers", []):
                    if not isinstance(layer, dict) or not is_rendered_visual_layer(layer):
                        continue
                    layer_reveal = layer.get("revealAtUnit", beat_unit)
                    if layer_reveal > beat_unit:
                        has_internal_reveal = True
                        break
                    for nested_key in ("bars", "nodes", "links"):
                        nested_items = layer.get(nested_key)
                        if not isinstance(nested_items, list):
                            continue
                        if any(
                            isinstance(item, dict)
                            and item.get("revealAtUnit", layer_reveal) > beat_unit
                            for item in nested_items
                        ):
                            has_internal_reveal = True
                            break
                    if has_internal_reveal:
                        break
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
                if isinstance(layer, dict) and is_rendered_visual_layer(layer)
            }
            if kinds and not (kinds & EXPRESSIVE_LAYER_KINDS):
                text_only_run += 1
                if text_only_run == 3:
                    warnings.append(
                        f"scene {scene_position} has 3+ consecutive beats with text/tint layers only; "
                        "use counter, bar-compare, network, dialogue, arrow/underline annotate, "
                        "or asset layers"
                    )
            else:
                text_only_run = 0

    return beat_count, warnings, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a case-video project contract.")
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--visual-warning-seconds",
        type=float,
        default=12.0,
        help="Warn when one Visual Beat exceeds this duration; does not fail validation.",
    )
    parser.add_argument(
        "--max-visual-gap-seconds",
        type=float,
        default=12.0,
        help="Maximum gap between semantic visual changes in strict visual mode.",
    )
    parser.add_argument(
        "--strict-visuals",
        action="store_true",
        help="Fail on visual-density, repeated-beat, hybrid-layer, and panel-overlap issues.",
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    if not project.is_dir():
        raise SystemExit(f"project directory not found: {project}")

    narration = project / "narration.txt"
    if not narration.is_file() or not narration.read_text(encoding="utf-8").strip():
        raise SystemExit(f"missing or empty narration: {narration}")
    authored_title = load_authored_title(project)

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

    storyboard_width = int(storyboard.get("width") or 1920)
    storyboard_height = int(storyboard.get("height") or 1080)
    if storyboard_height > storyboard_width:
        for position, scene in enumerate(scenes, start=1):
            vertical_mode = scene.get(
                "visualMode",
                "editorial" if scene.get("visualBeats") else "layout",
            )
            if vertical_mode != "editorial":
                raise SystemExit(
                    f"scene {position} uses visualMode {vertical_mode!r} on a vertical "
                    "canvas; vertical 9:16 projects must use editorial scenes because "
                    "the shared template layouts are 16:9-only"
                )

    contract_warnings: list[str] = []
    if authored_title is None:
        contract_warnings.append(
            "title.txt is missing; legacy project remains readable, but add it before the next production render"
        )
    cover = storyboard.get("cover")
    if cover is None:
        contract_warnings.append(
            "storyboard has no cover; legacy project will render without a frame-0 title cover"
        )
    else:
        if not isinstance(cover, dict):
            raise SystemExit("storyboard.cover must be an object")
        title = cover.get("title")
        if not isinstance(title, str) or not title.strip():
            raise SystemExit("storyboard.cover.title must be a non-empty string")
        if authored_title is not None and title.strip() != authored_title:
            raise SystemExit(
                "storyboard.cover.title must exactly match the canonical title in title.txt"
            )
        through_unit = cover.get("throughUnit")
        first_scene_first, first_scene_last = scenes[0]["units"]
        if isinstance(through_unit, bool) or not isinstance(through_unit, int):
            raise SystemExit("storyboard.cover.throughUnit must be an integer")
        if through_unit < first_scene_first or through_unit > first_scene_last:
            raise SystemExit(
                "storyboard.cover.throughUnit must be inside the first scene units "
                f"[{first_scene_first}, {first_scene_last}]"
            )
        cover_end_seconds = float(unit_by_index[through_unit].get("end") or 0)
        if through_unit > first_scene_first and cover_end_seconds > COVER_SPLASH_MAX_SECONDS:
            contract_warnings.append(
                f"storyboard.cover.throughUnit={through_unit} ends the title cover at "
                f"{cover_end_seconds:.1f}s; narration starts at 0s, so the engine clamps "
                f"the cover to the {COVER_SPLASH_MAX_SECONDS:.1f}s splash cap and the "
                "authored tail beyond the cap never renders"
            )
        for key in ("subtitle", "kicker"):
            if key in cover and not isinstance(cover[key], str):
                raise SystemExit(f"storyboard.cover.{key} must be a string")
        if len(title.replace("\n", "")) > 30:
            contract_warnings.append(
                "storyboard.cover.title is longer than 30 characters; inspect frame 0 for fit"
            )

    prompt_file_set = prompt_files(project)
    pool_assets = pool_asset_records(project)
    checked_images: set[str] = set()
    visual_assets = validate_visual_assets(
        project,
        storyboard,
        prompt_file_set,
        pool_assets,
        checked_images,
    )
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
            if cue.get("transition") not in BACKGROUND_TRANSITIONS:
                raise SystemExit(
                    f"scene {position} background {cue_position} has invalid transition: "
                    f"{cue.get('transition')!r}"
                )
            if cue.get("motion") not in BACKGROUND_MOTIONS:
                raise SystemExit(
                    f"scene {position} background {cue_position} has invalid motion: "
                    f"{cue.get('motion')!r}"
                )
            asset = image if image else video
            normalized_asset, asset_path = normalized_local_asset(
                project,
                asset,
                f"scene {position} background {cue_position}",
            )
            if image:
                validate_final_image_asset(
                    normalized_asset,
                    asset_path,
                    f"scene {position} background {cue_position}",
                    checked_images,
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

    visual_beat_count, visual_warnings, visual_errors = validate_visual_beats(
        scenes,
        visual_assets,
        unit_by_index,
        args.visual_warning_seconds,
        args.max_visual_gap_seconds,
        args.strict_visuals,
        storyboard_width,
        storyboard_height,
    )

    audio = storyboard.get("audio", "audio/narration_azure.wav")
    audio_path = project / audio
    if not audio_path.is_file():
        raise SystemExit(f"storyboard audio not found: {audio_path}")

    warnings = contract_warnings + visual_warnings
    for warning in warnings:
        print(f"warning: {warning}")
    if visual_errors:
        raise SystemExit(
            "strict visual validation failed:\n- " + "\n- ".join(visual_errors)
        )

    print(
        f"valid project={project} units={len(units)} scenes={len(scenes)} "
        f"backgrounds={background_count} visualAssets={len(visual_assets)} "
        f"poolAssets={len(pool_assets)} visualBeats={visual_beat_count} "
        f"warnings={len(warnings)} audio={audio}"
    )


if __name__ == "__main__":
    main()
