#!/usr/bin/env python3
"""Staged, low-cost readiness gates for case-video production.

The plan gate runs before image generation and rejects the scheduling failures
that previously produced repetitive manager videos.  The render gate reuses
the same checks, then validates real assets, portrait contracts, and an exact
frame-zero cover proof before a full Remotion render is allowed to start.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.app.services.visual_adapter import prompt_image_path

try:
    from character_portrait_pool import image_metrics
    from evaluate_visual_storyboard import evaluate_project, write_report
    from visual_beat_planning import is_rendered_visual_layer
except ModuleNotFoundError:  # pragma: no cover - supports package imports in tests
    from scripts.character_portrait_pool import image_metrics
    from scripts.evaluate_visual_storyboard import evaluate_project, write_report
    from scripts.visual_beat_planning import is_rendered_visual_layer


DEFAULT_MIN_SCORES = {"plan": 80.0, "render": 85.0}
BLOCKING_EVALUATION_CODES = {
    "disabled-annotate-shape",
    "long-visual-gap",
    "periodic-project-schedule",
    "periodic-scene-schedule",
    "stale-derived-storyboard",
    "template-concentration",
}
WHITE_BACKGROUND_MINIMUM = 225.0
PORTRAIT_COVERAGE_RANGE = (0.12, 0.72)
KNOWN_PORTRAIT_STYLES = {
    "manager": "manager-silhouette-warm",
    "sales": "sales-watercolor-blue-yellow",
}
PORTRAIT_STYLE_PROMPT_TERMS = {
    "manager": (
        "silhouette",
        "cut-paper",
        "screen-print",
        "deep navy",
        "burnt orange",
        "剪影",
        "剪纸",
        "丝网印刷",
        "深海军蓝",
        "焦橙",
    ),
    "sales": (
        "watercolor",
        "gouache",
        "cobalt",
        "cadmium yellow",
        "水彩",
        "水粉",
        "钴蓝",
        "镉黄",
    ),
}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    location: str | None = None


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    return pure.as_posix()


def authored_title(project: Path) -> tuple[str | None, str | None]:
    path = project / "title.txt"
    if not path.is_file():
        return None, "title.txt is required before production readiness."
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not lines[0].strip():
        return None, "title.txt must contain exactly one non-empty logical line."
    return lines[0].strip(), None


def prompt_records(project: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(project / "image_prompts.json", {}) or {}
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = payload.get("prompts") or payload.get("images") or payload.get("assets") or []
    else:
        records = []
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        target = normalize_relative_path(prompt_image_path(record))
        if target:
            result[target] = record
    return result


def pool_records(project: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(project / "asset_pool_usage.json", {}) or {}
    records = payload.get("assets", []) if isinstance(payload, dict) else []
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        src = normalize_relative_path(record.get("src"))
        if src:
            result[src] = record
    return result


def portrait_family(visual_style: str) -> str | None:
    lowered = visual_style.lower()
    if "manager" in lowered or "silhouette" in lowered:
        return "manager"
    if "sales" in lowered or "watercolor" in lowered:
        return "sales"
    return None


def prompt_text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key, ""))
        for key in ("fullPrompt", "prompt", "scenePrompt", "stylePrompt")
    ).lower()


def referenced_asset_ids(storyboard: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for scene in storyboard.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for beat in scene.get("visualBeats", []):
            if not isinstance(beat, dict):
                continue
            base_asset = beat.get("baseAsset")
            if isinstance(base_asset, str) and base_asset:
                result.add(base_asset)
            for layer in beat.get("layers", []):
                if not isinstance(layer, dict):
                    continue
                for key in ("asset", "portrait"):
                    value = layer.get(key)
                    if isinstance(value, str) and value:
                        result.add(value)
                for nested_key in ("nodes", "bars"):
                    for item in layer.get(nested_key, []) if isinstance(layer.get(nested_key), list) else []:
                        if not isinstance(item, dict):
                            continue
                        value = item.get("portrait") or item.get("asset")
                        if isinstance(value, str) and value:
                            result.add(value)
    return result


def portrait_asset_ids(storyboard: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for scene in storyboard.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for beat in scene.get("visualBeats", []):
            if not isinstance(beat, dict):
                continue
            for layer in beat.get("layers", []):
                if not isinstance(layer, dict):
                    continue
                portrait = layer.get("portrait")
                if isinstance(portrait, str) and portrait:
                    result.add(portrait)
                for nested_key in ("nodes", "bars"):
                    nested = layer.get(nested_key)
                    for item in nested if isinstance(nested, list) else []:
                        if not isinstance(item, dict):
                            continue
                        portrait = item.get("portrait")
                        if isinstance(portrait, str) and portrait:
                            result.add(portrait)
    for asset in storyboard.get("visualAssets", []):
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str):
            continue
        src = normalize_relative_path(asset.get("src")) or ""
        if (
            asset.get("type") == "portrait"
            or asset["id"].startswith(("portrait-", "person-"))
            or "/characters/" in f"/{src}"
        ):
            result.add(asset["id"])
    return result


def scene_background_paths(storyboard: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for scene in storyboard.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for cue in scene.get("backgrounds", []):
            if not isinstance(cue, dict):
                continue
            image = normalize_relative_path(cue.get("image"))
            if image:
                result.add(image)
    return result


def text_only_runs(storyboard: dict[str, Any]) -> list[tuple[str, int]]:
    runs: list[tuple[str, int]] = []
    for scene_position, scene in enumerate(storyboard.get("scenes", []), start=1):
        if not isinstance(scene, dict):
            continue
        longest = current = 0
        for beat in scene.get("visualBeats", []):
            layers = [
                layer
                for layer in beat.get("layers", [])
                if isinstance(layer, dict) and is_rendered_visual_layer(layer)
            ] if isinstance(beat, dict) else []
            expressive = any(
                layer.get("kind")
                in {"asset", "counter", "bar-compare", "network", "dialogue", "annotate"}
                for layer in layers
            )
            current = 0 if expressive else current + 1
            longest = max(longest, current)
        if longest >= 3:
            runs.append((str(scene.get("id") or f"scene-{scene_position:02d}"), longest))
    return runs


def validate_plan_contract(
    project: Path,
    storyboard: dict[str, Any],
    timeline: dict[str, Any],
    prompts: dict[str, dict[str, Any]],
    pool: dict[str, dict[str, Any]],
    repo_root: Path,
) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    units = timeline.get("units", []) if isinstance(timeline, dict) else []
    expected = list(range(1, len(units) + 1))
    indices = [unit.get("index") for unit in units if isinstance(unit, dict)]
    if not units or indices != expected:
        findings.append(Finding("blocker", "timeline-units", "Timeline units must be continuous from 1."))

    scenes = storyboard.get("scenes", []) if isinstance(storyboard, dict) else []
    covered: list[int] = []
    for position, scene in enumerate(scenes, start=1):
        bounds = scene.get("units") if isinstance(scene, dict) else None
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or not all(isinstance(value, int) for value in bounds)
            or bounds[0] > bounds[1]
        ):
            findings.append(
                Finding("blocker", "scene-units", "Scene must declare a valid [first,last] unit range.", f"scene-{position:02d}")
            )
            continue
        covered.extend(range(bounds[0], bounds[1] + 1))
    if expected and covered != expected:
        findings.append(Finding("blocker", "scene-coverage", "Scenes must cover every timeline unit exactly once."))

    source_title, title_error = authored_title(project)
    if title_error:
        findings.append(Finding("blocker", "title-source", title_error))

    cover = storyboard.get("cover")
    if not isinstance(cover, dict):
        findings.append(Finding("blocker", "cover-missing", "A frame-zero cover is required."))
    else:
        title = cover.get("title")
        through_unit = cover.get("throughUnit")
        if not isinstance(title, str) or not title.strip():
            findings.append(Finding("blocker", "cover-title", "Cover title must be non-empty."))
        elif source_title is not None and title.strip() != source_title:
            findings.append(
                Finding(
                    "blocker",
                    "title-source-mismatch",
                    "storyboard.cover.title must exactly match title.txt.",
                )
            )
        first_scene_units = scenes[0].get("units") if scenes and isinstance(scenes[0], dict) else None
        valid_first_scene_units = (
            isinstance(first_scene_units, list)
            and len(first_scene_units) == 2
            and all(isinstance(value, int) for value in first_scene_units)
            and first_scene_units[0] <= first_scene_units[1]
        )
        if (
            not valid_first_scene_units
            or not isinstance(through_unit, int)
            or through_unit not in range(first_scene_units[0], first_scene_units[1] + 1)
        ):
            findings.append(Finding("blocker", "cover-duration", "cover.throughUnit must fall inside the first scene."))
        for key in ("align", "textAlign", "anchor", "position"):
            value = cover.get(key)
            if isinstance(value, str) and value.lower() in {"left", "right", "start", "end"}:
                findings.append(Finding("blocker", "cover-off-center", f"storyboard.cover.{key} requests a non-centered cover."))

    visual_assets = {
        asset.get("id"): asset
        for asset in storyboard.get("visualAssets", [])
        if isinstance(asset, dict) and isinstance(asset.get("id"), str)
    }
    declared_paths = set(prompts) | set(pool)
    duplicate_ids = len(visual_assets) != len(
        [asset for asset in storyboard.get("visualAssets", []) if isinstance(asset, dict) and isinstance(asset.get("id"), str)]
    )
    if duplicate_ids:
        findings.append(Finding("blocker", "duplicate-visual-asset-id", "visualAssets IDs must be unique."))

    for asset_id, asset in visual_assets.items():
        src = normalize_relative_path(asset.get("src"))
        if not src:
            findings.append(Finding("blocker", "unsafe-asset-path", f"Visual asset {asset_id!r} has an invalid local path."))
            continue
        if src not in declared_paths:
            findings.append(
                Finding(
                    "blocker",
                    "undeclared-visual-asset",
                    f"{src} is not declared by image_prompts.json or asset_pool_usage.json.",
                    asset_id,
                )
            )
        origin = asset.get("origin")
        if origin == "generated" and src not in prompts:
            findings.append(Finding("blocker", "generated-asset-without-prompt", f"Generated asset {src} has no generation prompt.", asset_id))
        if origin == "curated" and src not in pool:
            findings.append(Finding("blocker", "curated-asset-without-provenance", f"Curated asset {src} has no pool provenance.", asset_id))

    for asset_id in sorted(referenced_asset_ids(storyboard)):
        if asset_id not in visual_assets:
            findings.append(Finding("blocker", "unknown-visual-asset", f"Visual Beat references unknown asset {asset_id!r}."))
    for src in sorted(scene_background_paths(storyboard)):
        if src not in declared_paths:
            findings.append(Finding("blocker", "undeclared-background", f"Scene background {src} is not declared."))

    beat_count = 0
    callback_count = 0
    editorial_scene_count = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        beats = [beat for beat in scene.get("visualBeats", []) if isinstance(beat, dict)]
        if scene.get("visualMode") in {"editorial", "hybrid"} and beats:
            editorial_scene_count += 1
            beat_count += len(beats)
            callback_count += sum(beat.get("purpose") == "callback" for beat in beats)
    callback_ratio = callback_count / max(1, beat_count)
    if beat_count >= 8 and callback_ratio > 0.25:
        findings.append(
            Finding(
                "blocker",
                "callback-overuse",
                f"Callbacks occupy {callback_ratio:.0%} of editorial/hybrid beats; the limit is 25%.",
            )
        )

    for scene_id, run_length in text_only_runs(storyboard):
        findings.append(
            Finding(
                "warning",
                "text-only-run",
                f"{run_length} consecutive beats rely on text/tint without a story-bearing layer.",
                scene_id,
            )
        )

    portrait_findings, portrait_summary = validate_portraits(
        project,
        storyboard,
        prompts,
        pool,
        repo_root,
        require_files=False,
    )
    findings.extend(portrait_findings)
    return findings, {
        "beatCount": beat_count,
        "callbackCount": callback_count,
        "callbackRatio": round(callback_ratio, 3),
        "editorialSceneCount": editorial_scene_count,
        "declaredGeneratedAssets": len(prompts),
        "declaredPoolAssets": len(pool),
        "portraits": portrait_summary,
    }


def validate_portraits(
    project: Path,
    storyboard: dict[str, Any],
    prompts: dict[str, dict[str, Any]],
    pool: dict[str, dict[str, Any]],
    repo_root: Path,
    *,
    require_files: bool,
) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    portrait_ids = portrait_asset_ids(storyboard)
    portraits = [
        asset
        for asset in storyboard.get("visualAssets", [])
        if isinstance(asset, dict) and asset.get("id") in portrait_ids
    ]
    catalog_payload = load_json(repo_root / "assets" / "character-portraits" / "catalog.json", {}) or {}
    catalog = {
        asset.get("id"): asset
        for asset in catalog_payload.get("assets", [])
        if isinstance(asset, dict) and isinstance(asset.get("id"), str)
    }
    family = portrait_family(str(storyboard.get("visualStyle", "")))
    expected_style = KNOWN_PORTRAIT_STYLES.get(family or "")
    summaries: list[dict[str, Any]] = []

    for portrait in portraits:
        asset_id = str(portrait.get("id") or "unnamed-portrait")
        src = normalize_relative_path(portrait.get("src"))
        if not src:
            findings.append(Finding("blocker", "portrait-path", "Portrait path is invalid.", asset_id))
            continue
        pool_record = pool.get(src)
        prompt_record = prompts.get(src)
        pool_asset_id = portrait.get("poolAssetId") or (pool_record or {}).get("assetId")
        catalog_record = catalog.get(pool_asset_id)
        declared_style = ((pool_record or {}).get("tags") or {}).get("style")
        if catalog_record and not declared_style:
            declared_style = catalog_record.get("style")
        if prompt_record and not declared_style:
            declared_style = prompt_record.get("style") or prompt_record.get("styleFamily")

        if pool_record:
            if portrait.get("poolAssetId") and portrait.get("poolAssetId") != pool_record.get("assetId"):
                findings.append(Finding("blocker", "portrait-provenance-mismatch", "poolAssetId does not match asset_pool_usage.json.", asset_id))
            if not catalog_record:
                findings.append(Finding("blocker", "portrait-catalog-missing", f"Portrait pool asset {pool_asset_id!r} is absent from the catalog.", asset_id))
            elif ((catalog_record.get("qa") or {}).get("visualReview") != "accepted"):
                findings.append(Finding("blocker", "portrait-not-reviewed", "Portrait has not passed visual review in the shared catalog.", asset_id))
        elif prompt_record:
            text = prompt_text(prompt_record)
            has_white = any(term in text for term in ("white background", "pure white", "白色背景", "纯白背景"))
            has_half_body = any(term in text for term in ("half-body", "half body", "chest-up", "waist-up", "半身", "胸像"))
            has_chinese = any(term in text for term in ("chinese", "中国"))
            if not has_white or not has_half_body or not has_chinese:
                findings.append(
                    Finding(
                        "blocker",
                        "portrait-prompt-contract",
                        "Generated portrait prompts must explicitly request a Chinese subject, a white background and a half-body/chest-up subject.",
                        asset_id,
                    )
                )
            family_terms = PORTRAIT_STYLE_PROMPT_TERMS.get(family or "", ())
            if family_terms and not any(term in text for term in family_terms):
                findings.append(
                    Finding(
                        "blocker",
                        "portrait-prompt-style",
                        f"Generated portrait prompt does not identify the {expected_style} video style family.",
                        asset_id,
                    )
                )
        else:
            findings.append(Finding("blocker", "portrait-without-provenance", "Portrait has neither a generation prompt nor character-pool provenance.", asset_id))

        if expected_style and declared_style and declared_style != expected_style:
            findings.append(
                Finding(
                    "blocker",
                    "portrait-style-mismatch",
                    f"Portrait style {declared_style!r} does not match video family {expected_style!r}.",
                    asset_id,
                )
            )
        elif expected_style and not declared_style and not prompt_record:
            findings.append(Finding("blocker", "portrait-style-unknown", "Portrait style cannot be verified against the video family.", asset_id))

        summary: dict[str, Any] = {
            "id": asset_id,
            "src": src,
            "style": declared_style,
            "poolAssetId": pool_asset_id,
        }
        path = project / src
        if require_files:
            if not path.is_file():
                findings.append(Finding("blocker", "portrait-file-missing", f"Portrait file does not exist: {src}", asset_id))
            else:
                metrics = image_metrics(path)
                summary["metrics"] = metrics
                if metrics["width"] != metrics["height"] or min(metrics["width"], metrics["height"]) < 512:
                    findings.append(Finding("blocker", "portrait-dimensions", "Portrait must be a square image of at least 512×512.", asset_id))
                if min(metrics["cornerWhiteMean"][:2]) < WHITE_BACKGROUND_MINIMUM:
                    findings.append(Finding("blocker", "portrait-background", "Portrait top background is not clean white.", asset_id))
                lower, upper = PORTRAIT_COVERAGE_RANGE
                if not lower <= metrics["subjectCoverage"] <= upper:
                    findings.append(Finding("blocker", "portrait-crop", "Portrait subject coverage is inconsistent with a half-body portrait.", asset_id))
                actual_hash = sha256_file(path)
                summary["sha256"] = actual_hash
                for source_name, record in (("asset_pool_usage.json", pool_record), ("portrait catalog", catalog_record)):
                    expected_hash = (record or {}).get("sha256")
                    if expected_hash and expected_hash != actual_hash:
                        findings.append(Finding("blocker", "portrait-hash-mismatch", f"Portrait differs from its {source_name} record.", asset_id))
        summaries.append(summary)
    return findings, {"count": len(portraits), "assets": summaries}


def run_validator(project: Path, repo_root: Path) -> tuple[list[Finding], dict[str, Any]]:
    command = [
        sys.executable,
        str(repo_root / "scripts" / "validate_case_project.py"),
        "--strict-visuals",
        str(project),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    warning_count = len(re.findall(r"^warning:", output, flags=re.MULTILINE))
    summary = {
        "command": command,
        "exitCode": result.returncode,
        "warningCount": warning_count,
        "output": output,
    }
    if result.returncode:
        return [Finding("blocker", "strict-validator", output or "Strict project validation failed.")], summary
    return [Finding("info", "strict-validator", f"Strict project validation passed with {warning_count} warning(s).")], summary


def analyze_cover_overlay(path: Path) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGBA")
    width, height = image.size
    alpha = image.getchannel("A").point(lambda value: 255 if value >= 8 else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("cover overlay is empty")
    left, top, right, bottom = bbox
    bbox_width = right - left
    bbox_height = bottom - top
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    square_size = min(width, height)
    square_left = (width - square_size) / 2
    square_right = square_left + square_size
    area_ratio = (bbox_width * bbox_height) / (width * height)
    square_area_ratio = (bbox_width * bbox_height) / (square_size * square_size)
    return {
        "width": width,
        "height": height,
        "bbox": [left, top, right, bottom],
        "bboxWidthRatio": round(bbox_width / width, 4),
        "bboxHeightRatio": round(bbox_height / height, 4),
        "bboxAreaRatio": round(area_ratio, 4),
        "bboxWidthSquareRatio": round(bbox_width / square_size, 4),
        "bboxHeightSquareRatio": round(bbox_height / square_size, 4),
        "bboxAreaSquareRatio": round(square_area_ratio, 4),
        "centerOffsetXRatio": round(abs(center_x - width / 2) / width, 4),
        "centerOffsetYRatio": round(abs(center_y - height / 2) / height, 4),
        "insideCenteredSquare": left >= square_left + 20 and right <= square_right - 20,
    }


def validate_cover_geometry(metrics: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if metrics["centerOffsetXRatio"] > 0.04 or metrics["centerOffsetYRatio"] > 0.05:
        findings.append(Finding("blocker", "cover-not-centered", "Cover copy/scrim group is not geometrically centered."))
    if not metrics["insideCenteredSquare"]:
        findings.append(Finding("blocker", "cover-square-crop", "Cover copy/scrim falls outside the centered 1:1 crop-safe area."))
    if metrics["bboxWidthSquareRatio"] > 0.94 or metrics["bboxAreaSquareRatio"] > 0.48:
        findings.append(Finding("blocker", "cover-scrim-too-large", "Cover overlay is too broad and hides too much background."))
    if metrics["bboxHeightSquareRatio"] > 0.68:
        findings.append(Finding("blocker", "cover-scrim-too-tall", "Cover overlay is too tall and hides too much background."))
    return findings


def render_cover_proof(project: Path, repo_root: Path) -> tuple[list[Finding], dict[str, Any]]:
    engine_root = Path(os.environ.get("CASE_VIDEO_ENGINE_ROOT", repo_root / "engine")).expanduser().resolve()
    remotion_root = engine_root / "remotion"
    remotion = remotion_root / "node_modules" / ".bin" / "remotion"
    sync_assets = engine_root / "scripts" / "sync_assets.sh"
    output_dir = project / "qa" / "readiness"
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_path = output_dir / "cover_frame0.png"
    overlay_path = output_dir / "cover_overlay.png"
    crop_path = output_dir / "cover_center_square.png"
    if not remotion.is_file():
        return [Finding("blocker", "remotion-missing", f"Remotion CLI not found: {remotion}")], {}
    if not sync_assets.is_file():
        return [Finding("blocker", "sync-assets-missing", f"sync_assets.sh not found: {sync_assets}")], {}

    env = dict(os.environ)
    env["VIDEO_PROJECT_DIR"] = str(project)
    commands = [
        ["bash", str(sync_assets)],
        [str(remotion), "still", "src/index.ts", "CaseVideoVideoOnly", str(frame_path), "--frame=0", "--overwrite"],
        [str(remotion), "still", "src/index.ts", "CaseVideoCoverOverlay", str(overlay_path), "--frame=0", "--overwrite"],
    ]
    logs: list[str] = []
    for command in commands:
        result = subprocess.run(
            command,
            cwd=remotion_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        logs.append("\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part))
        if result.returncode:
            return [Finding("blocker", "cover-proof-render", logs[-1] or f"Command failed: {command}")], {"commands": commands, "logs": logs}

    try:
        with Image.open(frame_path) as frame:
            frame = frame.convert("RGB")
            width, height = frame.size
            size = min(width, height)
            left = (width - size) // 2
            top = (height - size) // 2
            frame.crop((left, top, left + size, top + size)).save(crop_path)
        metrics = analyze_cover_overlay(overlay_path)
    except (OSError, ValueError) as exc:
        return [Finding("blocker", "cover-proof-analysis", str(exc))], {"commands": commands, "logs": logs}
    findings = validate_cover_geometry(metrics)
    if not findings:
        findings.append(Finding("info", "cover-proof", "Frame-zero cover is centered, square-crop safe, and compact."))
    return findings, {
        "frame": str(frame_path.relative_to(project)),
        "centerSquare": str(crop_path.relative_to(project)),
        "overlay": str(overlay_path.relative_to(project)),
        "metrics": metrics,
        "logs": logs,
    }


def evaluation_findings(
    report: dict[str, Any],
    storyboard: dict[str, Any],
    declared_paths: set[str],
    stage: str,
    min_score: float,
    plan_summary: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    visual_assets = {
        asset.get("id"): normalize_relative_path(asset.get("src"))
        for asset in storyboard.get("visualAssets", [])
        if isinstance(asset, dict) and isinstance(asset.get("id"), str)
    }
    for issue in report.get("issues", []):
        code = str(issue.get("code", "evaluation-issue"))
        severity = str(issue.get("severity", "warning"))
        message = str(issue.get("message", ""))
        deferred = False
        if stage == "plan" and code == "missing-visual-source":
            match = re.search(r"Visual source ['\"](.+?)['\"]", message)
            source_id = match.group(1) if match else None
            deferred = bool(source_id and visual_assets.get(source_id) in declared_paths)
        blocking = (severity == "error" and not deferred) or code in BLOCKING_EVALUATION_CODES
        if deferred:
            findings.append(Finding("info", "planned-asset-pending", message, issue.get("scene")))
        else:
            findings.append(Finding("blocker" if blocking else "warning", code, message, issue.get("scene")))

    score = float(report.get("score", 0.0))
    if score < min_score:
        findings.append(Finding("blocker", "evaluation-score", f"Visual evaluation score {score:.1f} is below the {min_score:.1f} {stage} threshold."))
    metrics = report.get("metrics", {})
    beat_count = int(metrics.get("beatCount", 0) or 0)
    if beat_count >= 12:
        unique_ratio = float(metrics.get("uniqueFingerprintRatio", 0.0) or 0.0)
        top_share = float(metrics.get("topFingerprintShare", 1.0) or 1.0)
        if unique_ratio < 0.28:
            findings.append(Finding("blocker", "structure-variety", f"Only {unique_ratio:.0%} of beats have distinct structural fingerprints; require at least 28%."))
        if top_share > 0.38:
            findings.append(Finding("blocker", "structure-dominance", f"One beat structure occupies {top_share:.0%} of the video; limit is 38%."))
        required_sources = max(
            math.ceil(plan_summary.get("beatCount", beat_count) * 0.22),
            math.ceil(plan_summary.get("editorialSceneCount", 0) * 0.75),
        )
        actual_sources = int(metrics.get("uniqueBaseAssetCount", 0) or 0)
        if actual_sources < required_sources:
            findings.append(
                Finding(
                    "blocker",
                    "base-asset-scarcity",
                    f"Only {actual_sources} distinct beat base assets support {beat_count} beats; require at least {required_sources}.",
                )
            )
    if float(metrics.get("explicitIntentRatio", 0.0) or 0.0) < 0.8:
        findings.append(Finding("blocker", "visual-intent-coverage", "At least 80% of Visual Beats must declare visualIntent explicitly."))
    if float(metrics.get("maxVisualGapSeconds", 999.0) or 999.0) > 12.0:
        findings.append(Finding("blocker", "semantic-gap", "Maximum semantic visual gap exceeds 12 seconds."))
    return findings


def input_hashes(project: Path, storyboard: dict[str, Any], stage: str) -> dict[str, str]:
    paths = [
        project / name
        for name in (
            "title.txt",
            "narration.txt",
            "narration.timeline.json",
            "storyboard_plan.json",
            "rich_storyboard.json",
            "image_prompts.json",
            "asset_pool_usage.json",
        )
    ]
    if stage == "render":
        for asset in storyboard.get("visualAssets", []):
            if isinstance(asset, dict):
                src = normalize_relative_path(asset.get("src"))
                if src:
                    paths.append(project / src)
        for src in scene_background_paths(storyboard):
            paths.append(project / src)
    result: dict[str, str] = {}
    for path in sorted(set(paths)):
        if path.is_file():
            result[str(path.relative_to(project))] = sha256_file(path)
    return result


def write_readiness_report(report: dict[str, Any]) -> Path:
    project = Path(report["project"])
    output_dir = project / "qa" / "readiness"
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = report["stage"]
    json_path = output_dir / f"{stage}.json"
    md_path = output_dir / f"{stage}.md"
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(payload, encoding="utf-8")
    (output_dir / "latest.json").write_text(payload, encoding="utf-8")

    lines = [
        f"# Case-video readiness: {stage}",
        "",
        f"Status: **{report['status'].upper()}**",
        "",
        f"Visual evaluation: **{report.get('evaluation', {}).get('score', 'n/a')}** "
        f"(minimum {report['minimumScore']})",
        "",
        "## Findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            location = f" ({finding['location']})" if finding.get("location") else ""
            lines.append(f"- **{finding['severity'].upper()} `{finding['code']}`**: {finding['message']}{location}")
    else:
        lines.append("- No findings.")
    if report.get("coverProof"):
        lines.extend(
            [
                "",
                "## Cover proof",
                "",
                f"- Full frame: `{report['coverProof'].get('frame')}`",
                f"- Center square: `{report['coverProof'].get('centerSquare')}`",
                f"- Overlay: `{report['coverProof'].get('overlay')}`",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def evaluate_readiness(
    project: Path,
    *,
    stage: str,
    min_score: float,
    repo_root: Path,
    run_strict_validator: bool = True,
    run_cover_proof: bool = True,
) -> dict[str, Any]:
    project = project.expanduser().resolve()
    findings: list[Finding] = []
    try:
        storyboard = load_json(project / "rich_storyboard.json")
        timeline = load_json(project / "narration.timeline.json")
        if not isinstance(storyboard, dict) or not isinstance(timeline, dict):
            raise ValueError("rich_storyboard.json and narration.timeline.json are required")
    except ValueError as exc:
        report = {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "project": str(project),
            "stage": stage,
            "minimumScore": min_score,
            "status": "failed",
            "findings": [asdict(Finding("blocker", "project-input", str(exc)))],
        }
        write_readiness_report(report)
        return report

    prompts = prompt_records(project)
    pool = pool_records(project)
    contract_findings, plan_summary = validate_plan_contract(
        project, storyboard, timeline, prompts, pool, repo_root
    )
    findings.extend(contract_findings)
    evaluation: dict[str, Any] = {}
    try:
        evaluation = evaluate_project(project)
        write_report(evaluation)
        findings.extend(
            evaluation_findings(
                evaluation,
                storyboard,
                set(prompts) | set(pool),
                stage,
                min_score,
                plan_summary,
            )
        )
    except (SystemExit, ValueError, OSError) as exc:
        findings.append(Finding("blocker", "evaluation-failed", str(exc)))

    validator_summary: dict[str, Any] | None = None
    cover_summary: dict[str, Any] | None = None
    if stage == "render":
        portrait_findings, portrait_summary = validate_portraits(
            project,
            storyboard,
            prompts,
            pool,
            repo_root,
            require_files=True,
        )
        findings.extend(portrait_findings)
        plan_summary["portraits"] = portrait_summary
        if run_strict_validator:
            validator_findings, validator_summary = run_validator(project, repo_root)
            findings.extend(validator_findings)
        if run_cover_proof and not any(finding.severity == "blocker" for finding in findings):
            cover_findings, cover_summary = render_cover_proof(project, repo_root)
            findings.extend(cover_findings)

    # De-duplicate repeated evaluator/metric messages while preserving order.
    unique_findings: list[Finding] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for finding in findings:
        key = (finding.severity, finding.code, finding.message, finding.location)
        if key not in seen:
            unique_findings.append(finding)
            seen.add(key)
    status = "passed" if not any(finding.severity == "blocker" for finding in unique_findings) else "failed"
    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "stage": stage,
        "minimumScore": min_score,
        "status": status,
        "inputHashes": input_hashes(project, storyboard, stage),
        "summary": plan_summary,
        "evaluation": {
            "score": evaluation.get("score"),
            "grade": evaluation.get("grade"),
            "metrics": evaluation.get("metrics", {}),
        },
        "validator": validator_summary,
        "coverProof": cover_summary,
        "findings": [asdict(finding) for finding in unique_findings],
    }
    write_readiness_report(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--stage", choices=("plan", "render"), default="render")
    parser.add_argument("--min-score", type=float)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-validator", action="store_true", help="Debug only: skip strict project validation")
    parser.add_argument("--skip-cover-proof", action="store_true", help="Debug only: skip frame-zero Remotion proof")
    parser.add_argument("--json", action="store_true", help="Print the full readiness report")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    min_score = args.min_score if args.min_score is not None else DEFAULT_MIN_SCORES[args.stage]
    report = evaluate_readiness(
        args.project,
        stage=args.stage,
        min_score=min_score,
        repo_root=args.repo_root.expanduser().resolve(),
        run_strict_validator=not args.skip_validator,
        run_cover_proof=not args.skip_cover_proof,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        blockers = sum(finding["severity"] == "blocker" for finding in report["findings"])
        warnings = sum(finding["severity"] == "warning" for finding in report["findings"])
        score = report.get("evaluation", {}).get("score")
        print(
            f"readiness {report['stage']} {report['status']}: "
            f"score={score if score is not None else 'n/a'} blockers={blockers} warnings={warnings}"
        )
        print(f"report: {Path(report['project']) / 'qa' / 'readiness' / (report['stage'] + '.md')}")
        for finding in report["findings"]:
            if finding["severity"] == "info":
                continue
            location = f" [{finding['location']}]" if finding.get("location") else ""
            print(f"- {finding['severity'].upper()} {finding['code']}{location}: {finding['message']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
