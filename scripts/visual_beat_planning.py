#!/usr/bin/env python3
"""Semantic Visual Beat planning helpers.

This module deliberately separates story intent from Remotion presentation.
Callers author a small set of content-bearing candidates; the scheduler anchors
them to narration units and applies intent presets only after that decision.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Sequence


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
SUPPORTED_ANNOTATE_SHAPES = {"arrow", "underline"}


def is_rendered_visual_layer(layer: dict[str, Any]) -> bool:
    return (
        layer.get("kind") != "annotate"
        or layer.get("shape") in SUPPORTED_ANNOTATE_SHAPES
    )


INTENT_PRESETS: dict[str, dict[str, str]] = {
    "context": {
        "purpose": "establish",
        "composition": "full-bleed",
        "camera": "breathe",
    },
    "protagonist": {
        "purpose": "identify",
        "composition": "portrait-left",
        "camera": "push-in",
    },
    "claim": {
        "purpose": "identify",
        "composition": "full-bleed",
        "camera": "static",
    },
    "evidence": {
        "purpose": "evidence",
        "composition": "evidence-collage",
        "camera": "push-in",
    },
    "relationship": {
        "purpose": "explain",
        "composition": "document-focus",
        "camera": "drift",
    },
    "mechanism": {
        "purpose": "explain",
        "composition": "split",
        "camera": "drift",
    },
    "decision": {
        "purpose": "escalate",
        "composition": "portrait-right",
        "camera": "push-in",
    },
    "consequence": {
        "purpose": "consequence",
        "composition": "evidence-collage",
        "camera": "pull-out",
    },
    "reflection": {
        "purpose": "reset",
        "composition": "full-bleed",
        "camera": "breathe",
    },
}


@dataclass(frozen=True)
class BeatCandidate:
    """One authored story decision that may become a Visual Beat."""

    key: str
    intent: str
    cue_texts: tuple[str, ...]
    layers: tuple[dict[str, Any], ...]
    priority: int = 50
    preferred_fraction: float | None = None
    anchor_policy: str = "semantic"
    purpose: str | None = None
    composition: str | None = None
    camera: str | None = None
    transition: str | None = None
    treatment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.intent not in VISUAL_INTENTS:
            raise ValueError(f"unknown Visual Beat intent: {self.intent!r}")
        if not self.key.strip():
            raise ValueError("Visual Beat candidate key must be non-empty")
        if self.anchor_policy not in {"start", "semantic", "end"}:
            raise ValueError(f"unknown anchor policy: {self.anchor_policy!r}")


def _normalized_text(value: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff.%]+", "", str(value or "").lower())


def semantic_tokens(value: object) -> set[str]:
    """Return compact Chinese/Latin/numeric tokens for cheap cue matching."""

    text = str(value or "").lower()
    tokens: set[str] = set()
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z]+|\d+(?:\.\d+)?%?", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            if len(part) <= 2:
                tokens.add(part)
            else:
                tokens.add(part)
                tokens.update(part[index : index + 2] for index in range(len(part) - 1))
        else:
            tokens.add(part)
    return tokens


def numeric_tokens(value: object) -> set[str]:
    return {
        token.rstrip("%")
        for token in re.findall(r"\d+(?:\.\d+)?%?", str(value or "").replace(",", ""))
    }


def text_alignment_score(cues: Iterable[object], narration_text: object) -> float:
    """Score a cue against narration text on a stable 0..1 scale."""

    narration = str(narration_text or "")
    narration_normalized = _normalized_text(narration)
    narration_terms = semantic_tokens(narration)
    narration_numbers = numeric_tokens(narration)
    best = 0.0
    for raw_cue in cues:
        cue = str(raw_cue or "").strip()
        if not cue:
            continue
        cue_normalized = _normalized_text(cue)
        cue_terms = semantic_tokens(cue)
        cue_numbers = numeric_tokens(cue)
        if not cue_terms:
            continue
        overlap = cue_terms & narration_terms
        recall = len(overlap) / max(1, len(cue_terms))
        precision = len(overlap) / max(1, len(narration_terms))
        number_recall = (
            len(cue_numbers & narration_numbers) / len(cue_numbers) if cue_numbers else 0.0
        )
        exact = 1.0 if cue_normalized and cue_normalized in narration_normalized else 0.0
        score = min(1.0, 0.52 * recall + 0.13 * precision + 0.22 * number_recall + 0.28 * exact)
        best = max(best, score)
    return best


def candidate_alignment_score(candidate: BeatCandidate, narration_text: object) -> float:
    return text_alignment_score(candidate.cue_texts, narration_text)


def _candidate_preference(
    candidate: BeatCandidate,
    position: int,
    count: int,
) -> float:
    if candidate.anchor_policy == "start":
        return 0.0
    if candidate.anchor_policy == "end":
        return 1.0
    if candidate.preferred_fraction is not None:
        return min(1.0, max(0.0, candidate.preferred_fraction))
    return 0.0 if count <= 1 else position / (count - 1)


def _candidate_unit_score(
    candidate: BeatCandidate,
    unit: int,
    *,
    first: int,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
    preferred_fraction: float,
) -> float:
    semantic = candidate_alignment_score(candidate, unit_by_index[unit].get("text", ""))
    preferred_unit = first + preferred_fraction * max(1, last - first)
    position_score = 1.0 - abs(unit - preferred_unit) / max(1, last - first)
    return semantic + 0.16 * position_score


def _best_unconstrained_unit(
    candidate: BeatCandidate,
    *,
    first: int,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
    preferred_fraction: float,
) -> tuple[int, float]:
    span = max(1, last - first)
    preferred_unit = first + preferred_fraction * span
    best_unit = first
    best_score = -1.0
    for unit in range(first, last + 1):
        semantic = candidate_alignment_score(candidate, unit_by_index[unit].get("text", ""))
        distance = abs(unit - preferred_unit) / span
        score = semantic + 0.16 * (1.0 - distance)
        if score > best_score:
            best_score = score
            best_unit = unit
    return best_unit, max(0.0, best_score)


def _select_candidates(candidates: Sequence[BeatCandidate], capacity: int) -> list[BeatCandidate]:
    if capacity <= 0:
        return []
    if len(candidates) <= capacity:
        return list(candidates)
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (-item[1].priority, item[0]),
    )[:capacity]
    selected_indexes = {index for index, _ in ranked}
    return [candidate for index, candidate in enumerate(candidates) if index in selected_indexes]


def _evenly_spaced_units(first: int, last: int, count: int) -> list[int]:
    if count <= 0 or last < first:
        return []
    if count == 1:
        return [first]
    span = last - first
    return [first + round(span * index / (count - 1)) for index in range(count)]


def _unit_start(unit_by_index: dict[int, dict[str, Any]], index: int) -> float:
    value = unit_by_index[index].get("start")
    return float(value) if isinstance(value, (int, float)) else float(index)


def _scene_end(unit_by_index: dict[int, dict[str, Any]], last: int) -> float:
    unit = unit_by_index[last]
    value = unit.get("end")
    if isinstance(value, (int, float)):
        return float(value)
    return _unit_start(unit_by_index, last) + 1.0


def _maximum_anchor_gap_seconds(
    anchors: Sequence[int],
    *,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
) -> float:
    times = [_unit_start(unit_by_index, anchor) for anchor in anchors]
    times.append(_scene_end(unit_by_index, last))
    return max((later - earlier for earlier, later in zip(times, times[1:])), default=0.0)


def _coverage_anchors(
    count: int,
    *,
    first: int,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
) -> list[int]:
    """Place beats at temporal quantiles as a last-mile coverage guardrail."""

    if count <= 0:
        return []
    if count == 1:
        return [first]
    scene_start = _unit_start(unit_by_index, first)
    duration = max(0.001, _scene_end(unit_by_index, last) - scene_start)
    anchors = [first]
    for position in range(1, count):
        lower = anchors[-1] + 1
        remaining = count - position - 1
        upper = last - remaining
        target = scene_start + duration * position / count
        anchor = min(
            range(lower, upper + 1),
            key=lambda index: abs(_unit_start(unit_by_index, index) - target),
        )
        anchors.append(anchor)
    return anchors


def _joint_semantic_coverage_anchors(
    ordered: Sequence[BeatCandidate],
    *,
    first: int,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
    max_gap_seconds: float = 12.0,
) -> list[int] | None:
    """Maximize cue alignment while enforcing ordered, gap-safe anchors.

    The first beat is the scene's governing thought and therefore starts with
    the scene. Remaining beats keep semantic order, but their exact units are
    solved jointly so a late strong match cannot create an empty visual zone.
    """

    if not ordered:
        return []
    if len(ordered) == 1:
        if _scene_end(unit_by_index, last) - _unit_start(unit_by_index, first) <= max_gap_seconds:
            return [first]
        return None

    states: dict[int, tuple[float, tuple[int, ...]]] = {
        first: (
            _candidate_unit_score(
                ordered[0],
                first,
                first=first,
                last=last,
                unit_by_index=unit_by_index,
                preferred_fraction=0.0,
            ),
            (first,),
        )
    }
    for position, candidate in enumerate(ordered[1:], start=1):
        remaining = len(ordered) - position - 1
        lower_bound = first + position
        upper_bound = last - remaining
        preference = _candidate_preference(candidate, position, len(ordered))
        next_states: dict[int, tuple[float, tuple[int, ...]]] = {}
        for unit in range(lower_bound, upper_bound + 1):
            unit_time = _unit_start(unit_by_index, unit)
            local_score = _candidate_unit_score(
                candidate,
                unit,
                first=first,
                last=last,
                unit_by_index=unit_by_index,
                preferred_fraction=preference,
            )
            best: tuple[float, tuple[int, ...]] | None = None
            for previous_unit, (score, path) in states.items():
                if previous_unit >= unit:
                    continue
                gap = unit_time - _unit_start(unit_by_index, previous_unit)
                if gap > max_gap_seconds:
                    continue
                candidate_state = (score + local_score, (*path, unit))
                if best is None or candidate_state[0] > best[0]:
                    best = candidate_state
            if best is not None:
                next_states[unit] = best
        states = next_states
        if not states:
            return None

    scene_end = _scene_end(unit_by_index, last)
    feasible = [
        state
        for unit, state in states.items()
        if scene_end - _unit_start(unit_by_index, unit) <= max_gap_seconds
    ]
    if not feasible:
        return None
    return list(max(feasible, key=lambda state: state[0])[1])


def _stage_nested_reveals(layer: dict[str, Any], beat_unit: int, final_unit: int) -> None:
    if final_unit < beat_unit:
        return
    kind = layer.get("kind")
    if kind == "bar-compare":
        items = layer.get("bars")
        if isinstance(items, list) and items:
            anchors = _evenly_spaced_units(beat_unit, final_unit, len(items))
            for item, anchor in zip(items, anchors):
                item.setdefault("revealAtUnit", anchor)
    elif kind == "network":
        nodes = layer.get("nodes")
        links = layer.get("links")
        nodes = nodes if isinstance(nodes, list) else []
        links = links if isinstance(links, list) else []
        total = len(nodes) + len(links)
        anchors = _evenly_spaced_units(beat_unit, final_unit, total)
        for item, anchor in zip([*nodes, *links], anchors):
            item.setdefault("revealAtUnit", anchor)


def _stage_beat_layers(beat: dict[str, Any], final_unit: int) -> None:
    beat_unit = int(beat["atUnit"])
    layers = beat.get("layers", [])
    for layer in layers:
        _stage_nested_reveals(layer, beat_unit, final_unit)

    counters = [
        layer
        for layer in layers
        if layer.get("kind") == "counter" and "revealAtUnit" not in layer
    ]
    if len(counters) > 1:
        anchors = _evenly_spaced_units(beat_unit, final_unit, len(counters))
        for layer, anchor in zip(counters, anchors):
            layer["revealAtUnit"] = anchor


def schedule_visual_beats(
    candidates: Sequence[BeatCandidate],
    *,
    scene_id: str,
    first: int,
    last: int,
    unit_by_index: dict[int, dict[str, Any]],
    base_asset: str | None,
    treatment: str = "natural",
) -> list[dict[str, Any]]:
    """Anchor authored candidates to units without inventing filler beats."""

    if first > last:
        raise ValueError(f"scene {scene_id} has invalid units [{first}, {last}]")
    if any(index not in unit_by_index for index in range(first, last + 1)):
        raise ValueError(f"scene {scene_id} references missing narration units")
    if not candidates:
        raise ValueError(f"scene {scene_id} has no authored Visual Beat candidates")

    selected = _select_candidates(candidates, last - first + 1)
    estimates: list[tuple[int, int, BeatCandidate]] = []
    for position, candidate in enumerate(selected):
        preference = _candidate_preference(candidate, position, len(selected))
        anchor, _ = _best_unconstrained_unit(
            candidate,
            first=first,
            last=last,
            unit_by_index=unit_by_index,
            preferred_fraction=preference,
        )
        estimates.append((anchor, position, candidate))
    start_items = [item for item in estimates if item[2].anchor_policy == "start"]
    semantic_items = [item for item in estimates if item[2].anchor_policy == "semantic"]
    end_items = [item for item in estimates if item[2].anchor_policy == "end"]
    ordered = [
        item[2]
        for item in [
            *sorted(start_items, key=lambda item: item[1]),
            *sorted(semantic_items, key=lambda item: (item[0], item[1])),
            *sorted(end_items, key=lambda item: item[1]),
        ]
    ]

    anchors = _joint_semantic_coverage_anchors(
        ordered,
        first=first,
        last=last,
        unit_by_index=unit_by_index,
    )
    if anchors is None:
        # An unusually long scene may not contain enough authored decisions to
        # satisfy the pacing guardrail. Keep the same candidates and expose the
        # gap to QA rather than fabricating a decorative filler beat.
        anchors = _coverage_anchors(
            len(ordered),
            first=first,
            last=last,
            unit_by_index=unit_by_index,
        )

    beats: list[dict[str, Any]] = []
    for position, (candidate, at_unit) in enumerate(zip(ordered, anchors), start=1):
        preset = INTENT_PRESETS[candidate.intent]
        beat: dict[str, Any] = {
            "id": f"{scene_id}-b{position:02d}",
            "atUnit": at_unit,
            "visualIntent": candidate.intent,
            "purpose": candidate.purpose or preset["purpose"],
            "composition": candidate.composition or preset["composition"],
            "transition": candidate.transition or ("dissolve" if position == 1 else "cut"),
            "camera": candidate.camera or preset["camera"],
            "treatment": candidate.treatment or treatment,
            "layers": [deepcopy(layer) for layer in candidate.layers],
        }
        if base_asset:
            beat["baseAsset"] = base_asset
        beat.update(deepcopy(candidate.metadata))
        beat.setdefault("candidateKey", candidate.key)
        beat.setdefault(
            "semanticCues",
            [cue for cue in candidate.cue_texts if isinstance(cue, str) and cue.strip()],
        )
        beats.append(beat)

    for position, beat in enumerate(beats):
        final_unit = (
            beats[position + 1]["atUnit"] - 1 if position + 1 < len(beats) else last
        )
        _stage_beat_layers(beat, final_unit)
    return beats


def infer_visual_intent(beat: dict[str, Any]) -> str:
    explicit = beat.get("visualIntent")
    if explicit in VISUAL_INTENTS:
        return str(explicit)
    layers = [
        layer
        for layer in beat.get("layers", [])
        if isinstance(layer, dict) and is_rendered_visual_layer(layer)
    ]
    kinds = {layer.get("kind") for layer in layers}
    purpose = beat.get("purpose")
    if "dialogue" in kinds:
        return "decision" if purpose == "escalate" else "protagonist"
    if kinds & {"counter", "bar-compare", "annotate"}:
        return "evidence"
    if "network" in kinds:
        return "relationship"
    return {
        "establish": "context",
        "identify": "claim",
        "evidence": "evidence",
        "explain": "mechanism",
        "escalate": "decision",
        "consequence": "consequence",
        "callback": "context",
        "reset": "reflection",
    }.get(str(purpose), "claim")


def network_topology(layer: dict[str, Any]) -> str:
    nodes = layer.get("nodes")
    links = layer.get("links")
    nodes = nodes if isinstance(nodes, list) else []
    links = links if isinstance(links, list) else []
    if len(nodes) < 2:
        return "invalid"
    if not links:
        return "unlinked"
    node_ids = {str(node.get("id")) for node in nodes if isinstance(node, dict)}
    degree = {node_id: 0 for node_id in node_ids}
    adjacency = {node_id: set() for node_id in node_ids}
    valid_links = 0
    for link in links:
        if not isinstance(link, dict):
            continue
        source = str(link.get("from"))
        target = str(link.get("to"))
        if source not in degree or target not in degree or source == target:
            continue
        valid_links += 1
        degree[source] += 1
        degree[target] += 1
        adjacency[source].add(target)
        adjacency[target].add(source)
    if valid_links == 0:
        return "unlinked"
    if len(nodes) == 2 and valid_links == 1:
        return "pair"
    if max(degree.values(), default=0) >= len(nodes) - 1 and len(nodes) >= 3:
        return "hub"

    visited: set[str] = set()
    pending = [next(iter(node_ids))]
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency[current] - visited)
    connected = len(visited) == len(node_ids)
    degrees = sorted(degree.values())
    if connected and valid_links == len(nodes) - 1 and degrees.count(1) == 2 and max(degrees) <= 2:
        return "chain"
    if connected and valid_links == len(nodes) and all(value == 2 for value in degrees):
        return "cycle"
    density = valid_links / max(1, len(nodes) * (len(nodes) - 1) / 2)
    if density >= 0.75:
        return "dense"
    return "sparse"


def beat_structure_fingerprint(beat: dict[str, Any]) -> str:
    layers = beat.get("layers", [])
    kinds: list[str] = []
    topologies: list[str] = []
    for layer in layers if isinstance(layers, list) else []:
        if not isinstance(layer, dict):
            continue
        if not is_rendered_visual_layer(layer):
            continue
        kind = str(layer.get("kind", "unknown"))
        kinds.append(kind)
        if kind == "network":
            topologies.append(network_topology(layer))
    return "|".join(
        [
            infer_visual_intent(beat),
            str(beat.get("composition", "unknown")),
            "+".join(sorted(kinds)) or "none",
            "+".join(sorted(topologies)) or "none",
        ]
    )


def beat_schedule_fingerprint(beat: dict[str, Any]) -> str:
    """Describe the visible template independently of authored story labels.

    Rich fingerprints intentionally include intent and composition. That is
    useful for editorial variety, but a cyclic scheduler can disguise the same
    layer template by rotating those labels. This compact fingerprint is used
    only to detect that presentation-level repetition.
    """

    layers = beat.get("layers", [])
    kinds: list[str] = []
    topologies: list[str] = []
    for layer in layers if isinstance(layers, list) else []:
        if not isinstance(layer, dict) or not is_rendered_visual_layer(layer):
            continue
        kind = str(layer.get("kind", "unknown"))
        kinds.append(kind)
        if kind == "network":
            topologies.append(network_topology(layer))
    return "|".join(
        [
            "+".join(kinds) or "empty",
            "+".join(topologies) or "none",
        ]
    )
