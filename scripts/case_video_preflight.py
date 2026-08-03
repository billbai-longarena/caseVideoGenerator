#!/usr/bin/env python3
"""Cheap, explicit preflight gates for one-shot case-video production.

The preflight is intentionally independent from the creative evaluator. It
checks the contracts that are cheap to verify before an expensive render:
content identity, vertical schema, compiled asset references, and the human
intent-frame review artifact.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

from PIL import Image, UnidentifiedImageError


FDE_OPENER = "这里是FDE不复杂，用真实的AI系统部署案例，帮您看懂变革、做对变革。"
FDE_CLOSER = "这期的《FDE不复杂》就到这里。看懂变革，做对变革，让AI系统真正落地。我们下期再见。"
FORBIDDEN_CONTRAST_PATTERNS = (
    re.compile(r"不是[^。！？\n]{0,48}(?:而是|是)"),
    re.compile(r"不是[^。！？\n]{0,48}[。！？]\s*是"),
)
VALID_PURPOSES = {
    "establish",
    "identify",
    "evidence",
    "explain",
    "escalate",
    "consequence",
    "callback",
    "reset",
}
VALID_ROLES = {"context", "person", "evidence", "document", "map", "metaphor", "texture"}
VALID_BACKGROUND_TRANSITIONS = {"wash", "paper", "ink", "flash", "push"}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    location: str | None = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add(findings: list[Finding], severity: str, code: str, message: str, location: str | None = None) -> None:
    findings.append(Finding(severity, code, message, location))


def rel_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return None
    return pure.as_posix()


def check_content(project: Path, findings: list[Finding]) -> None:
    title_path = project / "title.txt"
    narration_path = project / "narration.txt"
    if not title_path.is_file():
        add(findings, "error", "missing-title", "title.txt is required.")
    else:
        lines = title_path.read_text(encoding="utf-8").splitlines()
        if len(lines) != 1 or not lines[0].strip():
            add(findings, "error", "title-shape", "title.txt must contain one non-empty line.")

    if not narration_path.is_file():
        add(findings, "error", "missing-narration", "narration.txt is required.")
        return

    text = narration_path.read_text(encoding="utf-8").strip()
    if project.name.lower().startswith("fde_") or "fde" in project.name.lower():
        if not text.startswith(FDE_OPENER):
            add(findings, "error", "fde-opener", "Narration must start with the current FDE fixed opener.", "narration.txt")
        if not text.endswith(FDE_CLOSER):
            add(findings, "error", "fde-closer", "Narration must end with the current FDE fixed closer.", "narration.txt")

    for pattern in FORBIDDEN_CONTRAST_PATTERNS:
        match = pattern.search(text)
        if match:
            add(
                findings,
                "error",
                "forbidden-contrast",
                f"Rewrite prohibited contrast wording: {match.group(0)!r}.",
                "narration.txt",
            )
            break

    if re.search(r"\b(?:[A-Z])\s+(?:[A-Z])\b", text):
        add(findings, "error", "spaced-acronym", "Keep business acronyms contiguous in narration.", "narration.txt")

    case_inputs = project / "case_inputs.json"
    if project.name.lower().startswith("fde_") and not case_inputs.is_file():
        add(findings, "error", "missing-case-inputs", "FDE projects need case_inputs.json to lock the case boundary.", "case_inputs.json")


def iter_beats(plan: dict[str, Any]):
    for scene in plan.get("scenes", []):
        for beat in scene.get("visualBeats", []):
            yield scene, beat


def normalized_box(layer: dict[str, Any]) -> tuple[float, float, float, float] | None:
    box = layer.get("box")
    if not isinstance(box, dict):
        return None
    values = [box.get(key) for key in ("x", "y", "width", "height")]
    if not all(isinstance(value, (int, float)) for value in values):
        return None
    x, y, width, height = (float(value) for value in values)
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def boxes_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float], gap: float = 0.012) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return not (
        lx + lw + gap <= rx
        or rx + rw + gap <= lx
        or ly + lh + gap <= ry
        or ry + rh + gap <= ly
    )


def check_semantic_layer_composition(plan: dict[str, Any], findings: list[Finding]) -> None:
    """Catch the predictable dialogue/counter box collisions before rendering."""
    for scene, beat in iter_beats(plan):
        beat_id = beat.get("id", "unknown-beat")
        layers = [layer for layer in beat.get("layers", []) if isinstance(layer, dict)]
        semantic_layers = [layer for layer in layers if layer.get("kind") in {"dialogue", "counter"}]
        if not semantic_layers:
            continue
        for semantic in semantic_layers:
            semantic_box = normalized_box(semantic)
            if semantic_box is None:
                continue
            for other in layers:
                if other is semantic or other.get("kind") == "annotate":
                    continue
                other_box = normalized_box(other)
                if other_box is None or not boxes_overlap(semantic_box, other_box):
                    continue
                add(
                    findings,
                    "error",
                    "semantic-layer-overlap",
                    f"{semantic.get('kind')} layer overlaps {other.get('kind')} layer; reserve explicit non-overlapping boxes.",
                    beat_id,
                )


def check_plan(project: Path, findings: list[Finding]) -> None:
    plan_path = project / "storyboard_plan.json"
    if not plan_path.is_file():
        add(findings, "error", "missing-plan", "schema-v2 storyboard_plan.json is required.")
        return
    try:
        plan = load_json(plan_path)
    except Exception as exc:
        add(findings, "error", "invalid-plan", str(exc), "storyboard_plan.json")
        return

    if str(plan.get("version")) != "2":
        add(findings, "error", "plan-version", "storyboard_plan.json must declare version 2.", "storyboard_plan.json")
    canvas = plan.get("canvas") or {}
    if canvas.get("width") != 1080 or canvas.get("height") != 1920:
        add(findings, "error", "vertical-canvas", "Vertical projects must declare canvas 1080x1920.", "storyboard_plan.json")
    if plan.get("brand") != "FDE不复杂" or plan.get("subtitleLabel") != "FDE不复杂":
        add(findings, "error", "fde-brand", "FDE plan must use brand and subtitleLabel FDE不复杂.", "storyboard_plan.json")

    scenes = plan.get("scenes") or []
    if not scenes:
        add(findings, "error", "no-scenes", "At least one scene is required.", "storyboard_plan.json")
    for scene in scenes:
        sid = scene.get("id", "unknown-scene")
        if scene.get("visualMode") != "editorial":
            add(findings, "error", "vertical-visual-mode", "Every vertical scene must use visualMode editorial.", sid)
        if scene.get("layout") != "director-canvas":
            add(findings, "error", "vertical-layout", "Every vertical scene must use director-canvas.", sid)
        if not scene.get("backgrounds"):
            add(findings, "error", "scene-background", "Every scene needs an explicit background cue.", sid)
        for background in scene.get("backgrounds", []):
            if background.get("transition") not in VALID_BACKGROUND_TRANSITIONS:
                add(findings, "error", "background-transition", f"Unsupported background transition {background.get('transition')!r}.", sid)

    for asset in plan.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or "unknown-asset")
        role = asset.get("role")
        if role not in VALID_ROLES:
            add(findings, "error", "asset-role", f"Unsupported asset role {role!r}.", asset_id)
        if asset_id.startswith("bg-") and role == "person":
            add(findings, "error", "background-role", "bg-* assets must use a background/evidence role, not person.", asset_id)
        if asset_id.startswith("portrait-") and role != "person":
            add(findings, "error", "portrait-role", "portrait-* assets must use role person.", asset_id)

    for scene, beat in iter_beats(plan):
        bid = beat.get("id", "unknown-beat")
        purpose = beat.get("purpose")
        if purpose not in VALID_PURPOSES:
            add(findings, "error", "beat-purpose", f"Unsupported beat purpose {purpose!r}.", bid)
        if not beat.get("baseAsset") and not any(layer.get("kind") == "asset" for layer in beat.get("layers", [])):
            add(findings, "error", "beat-asset", "Every beat needs a baseAsset or asset layer.", bid)

    check_semantic_layer_composition(plan, findings)

    prompt_path = project / "image_prompts.json"
    if not prompt_path.is_file():
        add(findings, "error", "missing-prompts", "image_prompts.json is required.")
    else:
        try:
            prompts = load_json(prompt_path)
            if prompts.get("size") != "864x1536":
                add(findings, "error", "vertical-image-size", "Vertical image_prompts.json must declare size 864x1536.", "image_prompts.json")
        except Exception as exc:
            add(findings, "error", "invalid-prompts", str(exc), "image_prompts.json")


def check_render(project: Path, findings: list[Finding]) -> None:
    rich_path = project / "rich_storyboard.json"
    if not rich_path.is_file():
        add(findings, "error", "missing-rich-storyboard", "Build rich_storyboard.json before render preflight.")
        return
    try:
        rich = load_json(rich_path)
    except Exception as exc:
        add(findings, "error", "invalid-rich-storyboard", str(exc), "rich_storyboard.json")
        return

    visual_assets = {item.get("id"): item for item in rich.get("visualAssets", []) if isinstance(item, dict)}
    for asset_id, asset in visual_assets.items():
        src = rel_path(asset.get("src"))
        if not src:
            add(findings, "error", "asset-path", "Visual asset has no safe relative src.", str(asset_id))
            continue
        path = project / src
        if not path.is_file():
            add(findings, "error", "missing-asset", f"Missing visual asset: {src}.", str(asset_id))
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
            if asset.get("role") == "person":
                if (width, height) != (1024, 1024):
                    add(findings, "error", "portrait-size", f"Portrait must be 1024x1024, got {width}x{height}.", str(asset_id))
            elif (width, height) != (864, 1536):
                add(findings, "error", "background-size", f"Vertical background must be 864x1536, got {width}x{height}.", str(asset_id))
        except (UnidentifiedImageError, OSError) as exc:
            add(findings, "error", "invalid-asset", f"Cannot inspect {src}: {exc}.", str(asset_id))
        if asset.get("role") not in VALID_ROLES:
            add(findings, "error", "asset-role", f"Unsupported asset role {asset.get('role')!r}.", str(asset_id))

    review_path = project / "qa" / "intent-frame-review.json"
    if not review_path.is_file():
        add(findings, "error", "missing-intent-review", "Render requires qa/intent-frame-review.json with verdict pass.", str(review_path))
    else:
        try:
            review = load_json(review_path)
            if review.get("verdict") != "pass":
                add(findings, "error", "intent-review-failed", "Intent-frame review verdict must be pass.", str(review_path))
            frames = review.get("frames") or []
            failed = [frame for frame in frames if frame.get("verdict") != "pass"]
            if failed:
                add(findings, "error", "intent-frame-finding", f"{len(failed)} intent frames are not marked pass.", str(review_path))
        except Exception as exc:
            add(findings, "error", "invalid-intent-review", str(exc), str(review_path))

    manifest_path = project / "qa" / "intent-frames" / "manifest.json"
    if not manifest_path.is_file():
        add(findings, "error", "missing-intent-frames", "Render requires intent-frame images and manifest.", str(manifest_path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--stage", choices=("content", "plan", "render"), default="content")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"project not found: {project}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    check_content(project, findings)
    if args.stage in {"plan", "render"}:
        check_plan(project, findings)
    if args.stage == "render":
        check_render(project, findings)

    report_dir = project / "qa" / "preflight"
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "project": str(project),
        "stage": args.stage,
        "verdict": "fail" if any(item.severity == "error" for item in findings) else "pass",
        "findings": [asdict(item) for item in findings],
    }
    (report_dir / f"{args.stage}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    errors = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    if errors:
        print(f"preflight {args.stage} failed: errors={len(errors)} warnings={len(warnings)}")
        for item in errors:
            print(f"- ERROR {item.code}: {item.message}")
        return 1
    print(f"preflight {args.stage} passed: errors=0 warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
