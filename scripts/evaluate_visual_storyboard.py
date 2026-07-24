#!/usr/bin/env python3
"""Fast, render-free evaluation for case-video Visual Beat plans.

The evaluator intentionally uses only project-local storyboard, timeline, and
existing image assets. It is designed for scheduler iteration before TTS,
image generation, or a full Remotion render is repeated.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Iterable
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

try:
    from visual_beat_planning import (
        beat_schedule_fingerprint,
        beat_structure_fingerprint,
        infer_visual_intent,
        is_rendered_visual_layer,
        network_topology,
        text_alignment_score,
    )
except ModuleNotFoundError:  # pragma: no cover - supports module execution
    from scripts.visual_beat_planning import (
        beat_schedule_fingerprint,
        beat_structure_fingerprint,
        infer_visual_intent,
        is_rendered_visual_layer,
        network_topology,
        text_alignment_score,
    )


COMPONENT_WEIGHTS = {
    "pacing": 20.0,
    "semanticAlignment": 25.0,
    "structuralDiversity": 25.0,
    "visualSources": 15.0,
    "caseArc": 15.0,
}

CASE_ARC_GROUPS = {
    "orientation": {"context", "protagonist"},
    "claimAndProof": {"claim", "evidence"},
    "mechanism": {"relationship", "mechanism"},
    "agency": {"decision"},
    "payoff": {"consequence", "reflection"},
}

GENERIC_LINK_LABELS = {"影响", "推动", "决定", "连接", "关联", "作用"}


@dataclass(frozen=True)
class EvaluationIssue:
    severity: str
    code: str
    message: str
    scene: str | None = None
    beat: str | None = None


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"required file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def headline_text(scene: dict[str, Any]) -> str:
    headline = scene.get("headline", "")
    if isinstance(headline, dict):
        return str(headline.get("text", ""))
    return str(headline or "")


def timeline_text(unit_by_index: dict[int, dict[str, Any]], first: int, last: int) -> str:
    return "".join(
        str(unit_by_index[index].get("text", ""))
        for index in range(first, last + 1)
        if index in unit_by_index
    )


def cue_texts(value: Any) -> list[str]:
    """Collect visible semantic labels without treating technical IDs as cues."""

    cues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "label", "speaker", "sub"} and isinstance(item, str):
                if item.strip():
                    cues.append(item)
            elif key == "value" and isinstance(item, dict):
                numeric = "".join(
                    str(item.get(part, "")) for part in ("prefix", "from", "to", "suffix")
                )
                if numeric:
                    cues.append(numeric)
            elif key in {"bars", "nodes", "links"}:
                cues.extend(cue_texts(item))
    elif isinstance(value, list):
        for item in value:
            cues.extend(cue_texts(item))
    return cues


def beat_source_ids(beat: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    base_asset = beat.get("baseAsset")
    if isinstance(base_asset, str) and base_asset:
        sources.add(base_asset)
    for layer in beat.get("layers", []):
        if isinstance(layer, dict) and layer.get("kind") == "asset":
            asset = layer.get("asset")
            if isinstance(asset, str) and asset:
                sources.add(asset)
    return sources


def nested_event_units(beat: dict[str, Any]) -> set[int]:
    at_unit = beat.get("atUnit")
    if not isinstance(at_unit, int):
        return set()
    units = {at_unit}
    for layer in beat.get("layers", []):
        if not isinstance(layer, dict):
            continue
        if not is_rendered_visual_layer(layer):
            continue
        for key in ("revealAtUnit", "exitAtUnit"):
            if isinstance(layer.get(key), int):
                units.add(int(layer[key]))
        for nested_key in ("bars", "nodes", "links"):
            for item in layer.get(nested_key, []) if isinstance(layer.get(nested_key), list) else []:
                if isinstance(item, dict) and isinstance(item.get("revealAtUnit"), int):
                    units.add(int(item["revealAtUnit"]))
    return units


def event_seconds(
    event_units: Iterable[int],
    unit_by_index: dict[int, dict[str, Any]],
) -> list[float]:
    values = []
    for index in event_units:
        unit = unit_by_index.get(index)
        if unit is not None and isinstance(unit.get("start"), (int, float)):
            values.append(float(unit["start"]))
    return sorted(set(values))


def normalized_entropy(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 1 or len(counter) <= 1:
        return 0.0
    entropy = -sum((count / total) * math.log(count / total) for count in counter.values())
    return clamp(entropy / math.log(len(counter)))


def periodic_pattern(sequence: list[str]) -> dict[str, Any] | None:
    """Find a repeated scheduler cycle, allowing a small amount of variation."""

    if len(sequence) < 6:
        return None
    best: dict[str, Any] | None = None
    for period in range(2, min(8, len(sequence) // 2) + 1):
        comparisons = len(sequence) - period
        matches = sum(
            sequence[index] == sequence[index - period]
            for index in range(period, len(sequence))
        )
        accuracy = matches / comparisons
        if accuracy < 0.8:
            continue
        candidate = {
            "period": period,
            "accuracy": round(accuracy, 3),
            "repetitions": round(len(sequence) / period, 2),
        }
        if best is None or (candidate["accuracy"], -period) > (
            best["accuracy"],
            -best["period"],
        ):
            best = candidate
    return best


def grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def first_scene_image(
    project: Path,
    scene: dict[str, Any],
    asset_paths: dict[str, Path],
) -> Path | None:
    for beat in scene.get("visualBeats", []):
        if not isinstance(beat, dict):
            continue
        for source_id in beat_source_ids(beat):
            candidate = asset_paths.get(source_id)
            if candidate and candidate.is_file():
                return candidate
    for background in scene.get("backgrounds", []):
        if isinstance(background, dict) and isinstance(background.get("image"), str):
            candidate = project / background["image"]
            if candidate.is_file():
                return candidate
    return None


def evaluate_project(project: Path) -> dict[str, Any]:
    project = project.resolve()
    storyboard_path = project / "rich_storyboard.json"
    timeline_path = project / "narration.timeline.json"
    plan_path = project / "storyboard_plan.json"
    storyboard = load_json(storyboard_path)
    timeline = load_json(timeline_path)
    units = timeline.get("units", [])
    unit_by_index = {
        int(unit["index"]): unit
        for unit in units
        if isinstance(unit, dict) and isinstance(unit.get("index"), int)
    }
    if not unit_by_index:
        raise SystemExit(f"timeline has no indexed units: {project / 'narration.timeline.json'}")

    assets = {
        str(asset["id"]): asset
        for asset in storyboard.get("visualAssets", [])
        if isinstance(asset, dict) and isinstance(asset.get("id"), str)
    }
    asset_paths = {
        asset_id: project / str(asset.get("src", ""))
        for asset_id, asset in assets.items()
        if isinstance(asset.get("src"), str)
    }
    issues: list[EvaluationIssue] = []
    source_artifact_fresh: bool | None = None
    if plan_path.is_file():
        newest_source_mtime = max(plan_path.stat().st_mtime, timeline_path.stat().st_mtime)
        source_artifact_fresh = storyboard_path.stat().st_mtime >= newest_source_mtime
        if not source_artifact_fresh:
            issues.append(
                EvaluationIssue(
                    "error",
                    "stale-derived-storyboard",
                    "storyboard_plan.json or narration.timeline.json is newer than "
                    "rich_storyboard.json; rebuild before evaluating.",
                )
            )
    scene_reports: list[dict[str, Any]] = []
    all_fingerprints: list[str] = []
    all_schedule_fingerprints: list[str] = []
    all_intents: list[str] = []
    all_base_assets: set[str] = set()
    all_source_assets: set[str] = set()
    all_network_topologies: list[str] = []
    generic_hubs = 0
    explicit_intents = 0
    alignment_scores: list[float] = []
    local_alignment_scores: list[float] = []
    scene_alignment_scores: list[float] = []
    scene_source_diversities: list[float] = []
    scene_gap_values: list[float] = []
    missing_asset_refs: set[str] = set()
    annotation_without_cue = 0
    disabled_annotation_shapes: Counter[str] = Counter()
    periodic_scene_count = 0

    scenes = [scene for scene in storyboard.get("scenes", []) if isinstance(scene, dict)]
    for scene_position, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("id") or f"scene-{scene_position:02d}")
        raw_units = scene.get("units", [])
        if not isinstance(raw_units, list) or len(raw_units) != 2:
            issues.append(
                EvaluationIssue("error", "invalid-scene-units", "Scene lacks a [first,last] unit range.", scene_id)
            )
            continue
        first, last = int(raw_units[0]), int(raw_units[1])
        beats = [beat for beat in scene.get("visualBeats", []) if isinstance(beat, dict)]
        beat_reports: list[dict[str, Any]] = []
        scene_fingerprints: list[str] = []
        scene_schedule_fingerprints: list[str] = []
        scene_base_assets: set[str] = set()
        scene_source_assets: set[str] = set()
        scene_local_alignments: list[float] = []
        scene_contract_alignments: list[float] = []
        events: set[int] = {first}
        scene_narration = timeline_text(unit_by_index, first, last)

        for keyword in scene.get("keywords", []):
            if isinstance(keyword, dict) and isinstance(keyword.get("atUnit"), int):
                events.add(int(keyword["atUnit"]))
        for background in scene.get("backgrounds", []):
            if isinstance(background, dict) and isinstance(background.get("atUnit"), int):
                events.add(int(background["atUnit"]))

        for beat_position, beat in enumerate(beats):
            beat_id = str(beat.get("id") or f"{scene_id}-beat-{beat_position + 1:02d}")
            at_unit = int(beat.get("atUnit", first))
            next_unit = (
                int(beats[beat_position + 1].get("atUnit", last + 1)) - 1
                if beat_position + 1 < len(beats)
                else last
            )
            next_unit = max(at_unit, min(last, next_unit))
            intent = infer_visual_intent(beat)
            if isinstance(beat.get("visualIntent"), str):
                explicit_intents += 1
            fingerprint = beat_structure_fingerprint(beat)
            schedule_fingerprint = beat_schedule_fingerprint(beat)
            disabled_annotations: list[str] = []
            for layer in beat.get("layers", []):
                if not isinstance(layer, dict) or layer.get("kind") != "annotate":
                    continue
                if is_rendered_visual_layer(layer):
                    continue
                shape = layer.get("shape")
                shape_label = str(shape) if shape is not None else "implicit-box"
                disabled_annotation_shapes[shape_label] += 1
                disabled_annotations.append(shape_label)
            active_layers = [
                layer
                for layer in beat.get("layers", [])
                if isinstance(layer, dict) and is_rendered_visual_layer(layer)
            ]
            visible_cues = cue_texts(active_layers)
            authored_cues = [
                cue
                for cue in beat.get("semanticCues", [])
                if isinstance(cue, str) and cue.strip()
            ]
            segment_text = timeline_text(unit_by_index, at_unit, next_unit)
            visible_alignment = text_alignment_score(visible_cues, segment_text)
            authored_alignment = (
                text_alignment_score(authored_cues, segment_text)
                if authored_cues
                else visible_alignment
            )
            local_alignment = 0.75 * authored_alignment + 0.25 * visible_alignment
            visible_scene_alignment = text_alignment_score(visible_cues, scene_narration)
            authored_scene_alignment = (
                text_alignment_score(authored_cues, scene_narration)
                if authored_cues
                else visible_scene_alignment
            )
            scene_alignment = (
                0.75 * authored_scene_alignment + 0.25 * visible_scene_alignment
            )
            alignment = 0.55 * scene_alignment + 0.45 * local_alignment
            alignment_scores.append(alignment)
            local_alignment_scores.append(local_alignment)
            scene_alignment_scores.append(scene_alignment)
            scene_local_alignments.append(local_alignment)
            scene_contract_alignments.append(scene_alignment)
            source_ids = beat_source_ids(beat)
            scene_source_assets.update(source_ids)
            all_source_assets.update(source_ids)
            base_asset = beat.get("baseAsset")
            if isinstance(base_asset, str) and base_asset:
                scene_base_assets.add(base_asset)
                all_base_assets.add(base_asset)
            for source_id in source_ids:
                if source_id not in assets or not asset_paths.get(source_id, Path()).is_file():
                    missing_asset_refs.add(source_id)

            topologies: list[str] = []
            for layer in active_layers:
                if layer.get("kind") == "network":
                    topology = network_topology(layer)
                    topologies.append(topology)
                    all_network_topologies.append(topology)
                    links = layer.get("links", [])
                    labels = {
                        str(link.get("label", ""))
                        for link in links
                        if isinstance(link, dict) and link.get("label")
                    }
                    if topology == "hub" and labels and labels <= GENERIC_LINK_LABELS:
                        generic_hubs += 1
                if layer.get("kind") == "annotate":
                    has_local_cue = any(
                        isinstance(other, dict)
                        and other.get("kind") in {"text", "counter", "bar-compare", "dialogue"}
                        and cue_texts(other)
                        for other in beat.get("layers", [])
                    )
                    if not has_local_cue:
                        annotation_without_cue += 1

            events.update(nested_event_units(beat))
            scene_fingerprints.append(fingerprint)
            scene_schedule_fingerprints.append(schedule_fingerprint)
            all_fingerprints.append(fingerprint)
            all_schedule_fingerprints.append(schedule_fingerprint)
            all_intents.append(intent)
            beat_reports.append(
                {
                    "id": beat_id,
                    "atUnit": at_unit,
                    "intent": intent,
                    "explicitIntent": beat.get("visualIntent"),
                    "fingerprint": fingerprint,
                    "scheduleFingerprint": schedule_fingerprint,
                    "alignment": round(alignment, 3),
                    "localCueAlignment": round(local_alignment, 3),
                    "sceneCueAlignment": round(scene_alignment, 3),
                    "authoredCueAlignment": round(authored_alignment, 3),
                    "visibleCueAlignment": round(visible_alignment, 3),
                    "sources": sorted(source_ids),
                    "networkTopologies": topologies,
                    "disabledAnnotations": disabled_annotations,
                }
            )

        periodic = periodic_pattern(scene_schedule_fingerprints)
        if periodic:
            periodic_scene_count += 1
            issues.append(
                EvaluationIssue(
                    "warning",
                    "periodic-scene-schedule",
                    f"Beat structure repeats every {periodic['period']} beats "
                    f"({periodic['accuracy']:.0%} match).",
                    scene_id,
                )
            )

        if len(beats) >= 4 and len(scene_base_assets) <= 1:
            issues.append(
                EvaluationIssue(
                    "warning",
                    "single-base-asset-scene",
                    f"{len(beats)} beats rely on {len(scene_base_assets)} base image; overlays carry the full scene.",
                    scene_id,
                )
            )
        if beats:
            scene_source_diversities.append(
                clamp(len(scene_source_assets) / max(1.0, min(3.0, float(len(beats)))))
            )

        times = event_seconds(events, unit_by_index)
        end_unit = unit_by_index.get(last, {})
        if isinstance(end_unit.get("end"), (int, float)):
            times.append(float(end_unit["end"]))
        times = sorted(set(times))
        gaps = [later - earlier for earlier, later in zip(times, times[1:])]
        max_gap = max(gaps, default=0.0)
        scene_gap_values.append(max_gap)
        if max_gap > 12.0:
            issues.append(
                EvaluationIssue(
                    "warning",
                    "long-visual-gap",
                    f"Longest interval without a visual event is {max_gap:.1f}s.",
                    scene_id,
                )
            )

        image_path = first_scene_image(project, scene, asset_paths)
        scene_reports.append(
            {
                "id": scene_id,
                "headline": headline_text(scene),
                "units": [first, last],
                "beatCount": len(beats),
                "uniqueFingerprints": len(set(scene_fingerprints)),
                "baseAssets": sorted(scene_base_assets),
                "sourceAssets": sorted(scene_source_assets),
                "maxVisualGapSeconds": round(max_gap, 3),
                "averageSceneCueAlignment": round(
                    sum(scene_contract_alignments) / max(1, len(scene_contract_alignments)),
                    3,
                ),
                "averageLocalCueAlignment": round(
                    sum(scene_local_alignments) / max(1, len(scene_local_alignments)),
                    3,
                ),
                "periodicPattern": periodic,
                "previewImage": str(image_path.relative_to(project)) if image_path else None,
                "beats": beat_reports,
            }
        )

    beat_count = len(all_fingerprints)
    fingerprint_counts = Counter(all_fingerprints)
    topology_counts = Counter(all_network_topologies)
    intent_counts = Counter(all_intents)
    unique_ratio = len(fingerprint_counts) / max(1, beat_count)
    top_fingerprint_share = max(fingerprint_counts.values(), default=0) / max(1, beat_count)
    entropy = normalized_entropy(fingerprint_counts)
    project_periodic = periodic_pattern(all_schedule_fingerprints)
    if project_periodic:
        issues.append(
            EvaluationIssue(
                "warning",
                "periodic-project-schedule",
                f"The project repeats a {project_periodic['period']}-beat structural cycle "
                f"({project_periodic['accuracy']:.0%} match).",
            )
        )
    if beat_count >= 12 and unique_ratio < 0.22:
        issues.append(
            EvaluationIssue(
                "warning",
                "template-concentration",
                f"Only {len(fingerprint_counts)} structural fingerprints cover {beat_count} beats "
                f"({unique_ratio:.0%} unique).",
            )
        )

    dominant_topology = topology_counts.most_common(1)[0] if topology_counts else None
    dominant_topology_share = (
        dominant_topology[1] / len(all_network_topologies) if dominant_topology else 0.0
    )
    if len(all_network_topologies) >= 4 and dominant_topology_share > 0.75:
        issues.append(
            EvaluationIssue(
                "warning",
                "network-topology-dominance",
                f"{dominant_topology[0]!r} is used by {dominant_topology_share:.0%} of network beats.",
            )
        )
    if generic_hubs >= 3:
        issues.append(
            EvaluationIssue(
                "warning",
                "generic-hub-causality",
                f"{generic_hubs} hub diagrams use generic causal labels; verify that links are sourced from the case.",
            )
        )
    if annotation_without_cue:
        issues.append(
            EvaluationIssue(
                "warning",
                "unmotivated-annotation",
                f"{annotation_without_cue} annotation beats have no local evidence label or dialogue cue.",
            )
        )
    if disabled_annotation_shapes:
        shape_summary = ", ".join(
            f"{shape}={count}" for shape, count in sorted(disabled_annotation_shapes.items())
        )
        issues.append(
            EvaluationIssue(
                "warning",
                "disabled-annotate-shape",
                f"{sum(disabled_annotation_shapes.values())} legacy annotation layers are not "
                f"rendered or counted as visual events ({shape_summary}). Replace them with "
                "arrow, underline, or a focused crop.",
            )
        )
    for source_id in sorted(missing_asset_refs):
        issues.append(
            EvaluationIssue(
                "error",
                "missing-visual-source",
                f"Visual source {source_id!r} is absent from the manifest or filesystem.",
            )
        )

    explicit_intent_ratio = explicit_intents / max(1, beat_count)
    if beat_count and explicit_intent_ratio < 0.5:
        issues.append(
            EvaluationIssue(
                "info",
                "implicit-visual-intent",
                f"Only {explicit_intent_ratio:.0%} of beats declare visualIntent; legacy inference was used.",
            )
        )

    average_alignment = sum(alignment_scores) / max(1, len(alignment_scores))
    average_scene_alignment = sum(scene_alignment_scores) / max(
        1, len(scene_alignment_scores)
    )
    average_local_alignment = sum(local_alignment_scores) / max(
        1, len(local_alignment_scores)
    )
    low_alignment_count = sum(score < 0.12 for score in alignment_scores)
    low_scene_alignment_count = sum(score < 0.12 for score in scene_alignment_scores)
    low_local_alignment_count = sum(score < 0.12 for score in local_alignment_scores)
    if beat_count and low_scene_alignment_count / beat_count > 0.25:
        issues.append(
            EvaluationIssue(
                "warning",
                "scene-contract-mismatch",
                f"{low_scene_alignment_count}/{beat_count} beats are weakly supported by their "
                "scene's full narration; verify scene boundaries and content assignment.",
            )
        )
    if beat_count and low_local_alignment_count / beat_count > 0.35:
        issues.append(
            EvaluationIssue(
                "warning",
                "weak-local-scheduling",
                f"{low_local_alignment_count}/{beat_count} beats have weak support near their "
                "scheduled narration units; inspect semantic anchors.",
            )
        )
    if beat_count and low_alignment_count / beat_count > 0.3:
        issues.append(
            EvaluationIssue(
                "warning",
                "low-cue-alignment",
                f"{low_alignment_count}/{beat_count} beats have weak text-to-narration cue alignment.",
            )
        )

    covered_arc_groups = {
        group
        for group, intents in CASE_ARC_GROUPS.items()
        if intents & set(intent_counts)
    }
    for missing_group in sorted(set(CASE_ARC_GROUPS) - covered_arc_groups):
        issues.append(
            EvaluationIssue(
                "warning",
                "missing-case-arc-role",
                f"No beat represents the {missing_group} role in the case arc.",
            )
        )

    max_gap = max(scene_gap_values, default=0.0)
    pacing_factor = clamp(1.0 - max(0.0, max_gap - 10.0) / 14.0)
    pacing_component = COMPONENT_WEIGHTS["pacing"] * pacing_factor

    alignment_factor = clamp(average_alignment / 0.42)
    intent_variety_factor = clamp(len(intent_counts) / 7.0)
    authored_intent_factor = 0.5 + 0.5 * explicit_intent_ratio
    semantic_component = COMPONENT_WEIGHTS["semanticAlignment"] * (
        0.5 * alignment_factor + 0.3 * intent_variety_factor + 0.2 * authored_intent_factor
    )

    expected_unique = max(4.0, beat_count * 0.38)
    variety_factor = clamp(len(fingerprint_counts) / expected_unique)
    dominance_factor = clamp(1.0 - max(0.0, top_fingerprint_share - 0.18) / 0.42)
    periodic_factor = 1.0 - clamp(
        (periodic_scene_count + (2 if project_periodic else 0)) / max(2.0, len(scenes) * 0.55)
    )
    topology_factor = (
        1.0
        if len(all_network_topologies) < 4
        else clamp(1.0 - max(0.0, dominant_topology_share - 0.5) / 0.5)
    )
    structural_component = COMPONENT_WEIGHTS["structuralDiversity"] * (
        0.45 * variety_factor
        + 0.2 * dominance_factor
        + 0.25 * periodic_factor
        + 0.1 * topology_factor
    )

    scene_source_factor = (
        sum(scene_source_diversities) / len(scene_source_diversities)
        if scene_source_diversities
        else 0.0
    )
    project_source_factor = clamp(len(all_base_assets) / max(1.0, float(len(scenes))))
    source_validity_factor = 1.0 - clamp(len(missing_asset_refs) / max(1.0, len(all_source_assets)))
    visual_sources_component = COMPONENT_WEIGHTS["visualSources"] * (
        0.65 * scene_source_factor
        + 0.25 * project_source_factor
        + 0.1 * source_validity_factor
    )

    arc_component = COMPONENT_WEIGHTS["caseArc"] * (
        len(covered_arc_groups) / len(CASE_ARC_GROUPS)
    )

    components = {
        "pacing": round(pacing_component, 2),
        "semanticAlignment": round(semantic_component, 2),
        "structuralDiversity": round(structural_component, 2),
        "visualSources": round(visual_sources_component, 2),
        "caseArc": round(arc_component, 2),
    }
    score = round(sum(components.values()), 1)
    return {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "title": storyboard.get("title") or storyboard.get("project", {}).get("title") or project.name,
        "score": score,
        "grade": grade(score),
        "components": components,
        "componentWeights": COMPONENT_WEIGHTS,
        "metrics": {
            "sceneCount": len(scenes),
            "beatCount": beat_count,
            "explicitIntentRatio": round(explicit_intent_ratio, 3),
            "intentCounts": dict(sorted(intent_counts.items())),
            "averageCueAlignment": round(average_alignment, 3),
            "averageSceneCueAlignment": round(average_scene_alignment, 3),
            "averageLocalCueAlignment": round(average_local_alignment, 3),
            "lowAlignmentBeatCount": low_alignment_count,
            "lowSceneAlignmentBeatCount": low_scene_alignment_count,
            "lowLocalAlignmentBeatCount": low_local_alignment_count,
            "uniqueFingerprintCount": len(fingerprint_counts),
            "uniqueFingerprintRatio": round(unique_ratio, 3),
            "topFingerprintShare": round(top_fingerprint_share, 3),
            "fingerprintEntropy": round(entropy, 3),
            "periodicSceneCount": periodic_scene_count,
            "projectPeriodicPattern": project_periodic,
            "disabledAnnotationShapeCounts": dict(sorted(disabled_annotation_shapes.items())),
            "networkTopologyCounts": dict(sorted(topology_counts.items())),
            "dominantNetworkTopologyShare": round(dominant_topology_share, 3),
            "uniqueBaseAssetCount": len(all_base_assets),
            "uniqueSourceAssetCount": len(all_source_assets),
            "maxVisualGapSeconds": round(max_gap, 3),
            "coveredCaseArcRoles": sorted(covered_arc_groups),
            "sourceArtifactFresh": source_artifact_fresh,
        },
        "issues": [asdict(issue) for issue in issues],
        "scenes": scene_reports,
    }


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Visual evaluation: {report['title']}",
        "",
        f"Score: **{report['score']}/100 ({report['grade']})**",
        "",
        "## Components",
        "",
        "| Component | Score | Maximum |",
        "|---|---:|---:|",
    ]
    for key, value in report["components"].items():
        lines.append(f"| {key} | {value:.2f} | {report['componentWeights'][key]:.0f} |")
    lines.extend(["", "## Issues", ""])
    if report["issues"]:
        for issue in report["issues"]:
            location = " / ".join(part for part in (issue.get("scene"), issue.get("beat")) if part)
            suffix = f" ({location})" if location else ""
            lines.append(
                f"- **{issue['severity'].upper()} `{issue['code']}`**: {issue['message']}{suffix}"
            )
    else:
        lines.append("- No issues detected.")
    lines.extend(["", "## Scenes", ""])
    for scene in report["scenes"]:
        periodic = scene.get("periodicPattern")
        cycle = f", cycle={periodic['period']}" if periodic else ""
        lines.append(
            f"- `{scene['id']}`: {scene['beatCount']} beats, "
            f"{scene['uniqueFingerprints']} fingerprints, "
            f"scene/local={scene['averageSceneCueAlignment']:.2f}/"
            f"{scene['averageLocalCueAlignment']:.2f}, "
            f"gap={scene['maxVisualGapSeconds']:.1f}s{cycle}"
        )
    return "\n".join(lines) + "\n"


def report_html(report: dict[str, Any], output_dir: Path) -> str:
    project = Path(report["project"])
    component_cards = "".join(
        f'<div class="metric"><strong>{html.escape(key)}</strong>'
        f'<span>{value:.1f}/{report["componentWeights"][key]:.0f}</span></div>'
        for key, value in report["components"].items()
    )
    issue_cards = "".join(
        f'<li class="{html.escape(issue["severity"])}"><code>{html.escape(issue["code"])}</code> '
        f'{html.escape(issue["message"])}'
        f'{" — " + html.escape(issue["scene"]) if issue.get("scene") else ""}</li>'
        for issue in report["issues"]
    ) or "<li>No issues detected.</li>"
    scene_cards = []
    for scene in report["scenes"]:
        image_markup = '<div class="image empty">no local preview</div>'
        if scene.get("previewImage"):
            image_path = project / scene["previewImage"]
            relative = os.path.relpath(image_path, output_dir).replace(os.sep, "/")
            image_markup = f'<img class="image" src="{quote(relative, safe="/")}" alt="">'
        beats = "".join(
            f'<span class="beat" title="{html.escape(beat["fingerprint"])} · '
            f'scene {beat["sceneCueAlignment"]:.2f} · local {beat["localCueAlignment"]:.2f}">'
            f'u{beat["atUnit"]} · {html.escape(beat["intent"])}</span>'
            for beat in scene["beats"]
        )
        cycle = scene.get("periodicPattern")
        cycle_text = f" · cycle {cycle['period']}" if cycle else ""
        scene_cards.append(
            '<article class="scene">'
            f'{image_markup}<div class="scene-body"><h3>{html.escape(scene["id"])} · '
            f'{html.escape(scene["headline"])}</h3><p>{scene["beatCount"]} beats · '
            f'{scene["uniqueFingerprints"]} structures · max gap '
            f'{scene["maxVisualGapSeconds"]:.1f}s · scene/local '
            f'{scene["averageSceneCueAlignment"]:.2f}/'
            f'{scene["averageLocalCueAlignment"]:.2f}{cycle_text}</p>'
            f'<div class="beats">{beats}</div>'
            "</div></article>"
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visual evaluation · {html.escape(str(report['title']))}</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; background:#08111f; color:#edf4ff; }}
body {{ max-width:1240px; margin:auto; padding:32px; }} h1,h2,h3,p {{ margin-top:0; }}
.hero {{ display:flex; align-items:end; justify-content:space-between; gap:24px; }}
.score {{ font-size:52px; font-weight:800; color:#ffd05b; }}
.metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin:24px 0; }}
.metric {{ background:#12233b; border:1px solid #25456d; padding:14px; border-radius:12px; display:flex; justify-content:space-between; }}
.issues {{ background:#101c2f; border-radius:14px; padding:20px 38px; line-height:1.55; }}
.issues li {{ margin:7px 0; }} .warning code {{ color:#ffd05b; }} .error code {{ color:#ff8080; }} .info code {{ color:#7dcaff; }}
.scenes {{ display:grid; gap:16px; margin-top:16px; }} .scene {{ display:grid; grid-template-columns:280px 1fr; background:#101c2f; border:1px solid #213a5d; border-radius:14px; overflow:hidden; }}
.image {{ width:280px; height:158px; object-fit:cover; background:#18283e; }} .empty {{ display:grid; place-items:center; color:#8ba0bb; }}
.scene-body {{ padding:16px 18px; }} .scene-body p {{ color:#aebed2; }} .beats {{ display:flex; flex-wrap:wrap; gap:7px; }}
.beat {{ font-size:12px; padding:5px 8px; border-radius:999px; background:#18385e; color:#dcebff; }}
@media (max-width:760px) {{ body {{padding:18px}} .scene {{grid-template-columns:1fr}} .image {{width:100%;height:auto;aspect-ratio:16/9}} .hero {{display:block}} }}
</style></head><body>
<div class="hero"><div><p>Render-free storyboard evaluation</p><h1>{html.escape(str(report['title']))}</h1></div><div class="score">{report['score']} · {report['grade']}</div></div>
<div class="metrics">{component_cards}</div>
<h2>Issues</h2><ul class="issues">{issue_cards}</ul>
<h2 style="margin-top:32px">Scenes</h2><div class="scenes">{''.join(scene_cards)}</div>
</body></html>"""


def write_contact_sheet(report: dict[str, Any], output_path: Path) -> None:
    project = Path(report["project"])
    scenes = report["scenes"]
    columns = 3
    tile_width, tile_height = 480, 306
    rows = max(1, math.ceil(len(scenes) / columns))
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "#08111f")
    draw = ImageDraw.Draw(sheet)
    for position, scene in enumerate(scenes):
        x = (position % columns) * tile_width
        y = (position // columns) * tile_height
        canvas = Image.new("RGB", (tile_width, 270), "#18283e")
        if scene.get("previewImage"):
            image_path = project / scene["previewImage"]
            try:
                with Image.open(image_path) as source:
                    canvas = ImageOps.fit(source.convert("RGB"), (tile_width, 270))
            except (OSError, UnidentifiedImageError):
                pass
        sheet.paste(canvas, (x, y))
        draw.rectangle((x, y + 270, x + tile_width, y + tile_height), fill="#101c2f")
        cycle = scene.get("periodicPattern")
        cycle_label = f" cycle={cycle['period']}" if cycle else ""
        draw.text(
            (x + 12, y + 281),
            f"{scene['id']}  beats={scene['beatCount']}  structures={scene['uniqueFingerprints']}{cycle_label}",
            fill="#edf4ff",
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=88)


def write_report(report: dict[str, Any]) -> Path:
    project = Path(report["project"])
    output_dir = project / "qa" / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "visual_eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "visual_eval.md").write_text(report_markdown(report), encoding="utf-8")
    (output_dir / "index.html").write_text(report_html(report, output_dir), encoding="utf-8")
    write_contact_sheet(report, output_dir / "contact_sheet.jpg")
    return output_dir


def terminal_summary(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    warning_count = sum(issue["severity"] == "warning" for issue in report["issues"])
    error_count = sum(issue["severity"] == "error" for issue in report["issues"])
    return (
        f"{Path(report['project']).name}: {report['score']}/100 ({report['grade']}) | "
        f"beats {metrics['beatCount']} | structures {metrics['uniqueFingerprintCount']} "
        f"({metrics['uniqueFingerprintRatio']:.0%}) | max gap {metrics['maxVisualGapSeconds']:.1f}s | "
        f"issues {error_count}E/{warning_count}W"
    )


def comparison(primary: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary": primary,
        "comparison": other,
        "delta": {
            "score": round(primary["score"] - other["score"], 1),
            "components": {
                key: round(primary["components"][key] - other["components"][key], 2)
                for key in COMPONENT_WEIGHTS
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Case-video project directory")
    parser.add_argument("--compare", type=Path, help="Evaluate a second project and print score deltas")
    parser.add_argument("--no-write", action="store_true", help="Do not create qa/evaluation artifacts")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON")
    parser.add_argument("--fail-under", type=float, default=None, help="Exit 1 when the primary score is lower")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    primary = evaluate_project(args.project)
    other = evaluate_project(args.compare) if args.compare else None
    payload: dict[str, Any] = comparison(primary, other) if other else primary

    if not args.no_write:
        output_dir = write_report(primary)
    else:
        output_dir = None

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(terminal_summary(primary))
        if other:
            print(terminal_summary(other))
            print(f"score delta: {primary['score'] - other['score']:+.1f}")
        if output_dir:
            print(f"report: {output_dir / 'index.html'}")
        for issue in primary["issues"][:12]:
            location = f" [{issue['scene']}]" if issue.get("scene") else ""
            print(f"- {issue['severity'].upper()} {issue['code']}{location}: {issue['message']}")
        if len(primary["issues"]) > 12:
            print(f"- ... {len(primary['issues']) - 12} more issues in the report")

    if args.fail_under is not None and primary["score"] < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
