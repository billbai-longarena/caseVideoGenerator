from __future__ import annotations

from typing import Any


def select_intent_frames(
    storyboard: dict[str, Any],
    timeline: dict[str, Any],
    *,
    max_frames: int = 24,
) -> list[dict[str, Any]]:
    """Select settled frames that cover every scene and then remaining beats."""

    fps = int(storyboard.get("fps", 30))
    if fps <= 0:
        raise ValueError("storyboard fps must be positive")
    units = timeline.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("timeline units must be a non-empty array")
    timeline_by_index = {
        int(unit["index"]): unit
        for unit in units
        if isinstance(unit, dict) and isinstance(unit.get("index"), int)
    }
    if len(timeline_by_index) != len(units):
        raise ValueError("timeline unit indices must be unique integers")

    raw_scenes = storyboard.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("storyboard scenes must be a non-empty array")
    total_duration = float(timeline.get("duration") or units[-1].get("end") or 0)
    last_frame = max(0, round(total_duration * fps) - 1)
    candidates: list[dict[str, Any]] = []
    scene_first_candidate: dict[str, int] = {}

    for scene_position, scene in enumerate(raw_scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"storyboard scene {scene_position + 1} must be an object")
        scene_id = str(scene.get("id", "")).strip()
        scene_units = scene.get("units")
        if not scene_id or not isinstance(scene_units, list) or len(scene_units) != 2:
            raise ValueError(f"storyboard scene {scene_position + 1} requires id and units")
        first_unit, last_unit = int(scene_units[0]), int(scene_units[1])
        if first_unit not in timeline_by_index or last_unit not in timeline_by_index:
            raise ValueError(f"scene {scene_id} is outside the narration timeline")

        raw_beats = scene.get("visualBeats")
        beats = raw_beats if isinstance(raw_beats, list) and raw_beats else [None]
        for beat_position, beat in enumerate(beats):
            if beat is not None and not isinstance(beat, dict):
                raise ValueError(f"scene {scene_id} visual beat {beat_position + 1} must be an object")
            at_unit = int(beat.get("atUnit", first_unit)) if beat is not None else first_unit
            if at_unit not in timeline_by_index or not first_unit <= at_unit <= last_unit:
                raise ValueError(f"scene {scene_id} visual beat is outside its scene")

            next_unit = None
            if beat_position + 1 < len(beats):
                next_beat = beats[beat_position + 1]
                if isinstance(next_beat, dict):
                    next_unit = int(next_beat["atUnit"])
            start_seconds = float(timeline_by_index[at_unit]["start"])
            end_seconds = (
                float(timeline_by_index[next_unit]["start"])
                if next_unit is not None
                else float(timeline_by_index[last_unit]["end"])
            )
            sample_seconds = _settled_sample(start_seconds, end_seconds)
            beat_id = (str(beat.get("id", "")).strip() or None) if beat is not None else None
            record = {
                "scene_id": scene_id,
                "beat_id": beat_id,
                "frame": min(last_frame, max(0, round(sample_seconds * fps))),
                "seconds": round(sample_seconds, 3),
                "scene_units": [first_unit, last_unit],
                "dramatic_function": str(scene.get("dramaticFunction", "")),
                "scene_directorial_intent": str(scene.get("directorialIntent", "")),
                "beat_directorial_intent": str(beat.get("directorialIntent", "")) if beat is not None else "",
            }
            if scene_id not in scene_first_candidate:
                scene_first_candidate[scene_id] = len(candidates)
            candidates.append(record)

    required_indices = list(scene_first_candidate.values())
    effective_limit = max(len(required_indices), max(1, max_frames))
    selected_indices = set(required_indices)
    remaining = [index for index in range(len(candidates)) if index not in selected_indices]
    available_slots = max(0, effective_limit - len(selected_indices))
    selected_indices.update(_evenly_spaced_indices(remaining, available_slots))

    selected = [candidates[index] for index in sorted(selected_indices, key=lambda item: candidates[item]["frame"])]
    for position, record in enumerate(selected, start=1):
        record["frame_id"] = f"frame-{position:03d}"
        record["file"] = f"frame-{position:03d}.png"
    return selected


def intent_frame_description(record: dict[str, Any]) -> str:
    parts = [
        f"frame_id={record['frame_id']}",
        f"scene_id={record['scene_id']}",
        f"beat_id={record.get('beat_id') or 'none'}",
        f"seconds={record['seconds']}",
        f"dramatic_function={record.get('dramatic_function', '')}",
        f"scene_intent={record.get('scene_directorial_intent', '')}",
        f"beat_intent={record.get('beat_directorial_intent', '')}",
    ]
    return " | ".join(parts)

def _settled_sample(start_seconds: float, end_seconds: float) -> float:
    span = max(0.0, end_seconds - start_seconds)
    if span <= 0.2:
        return start_seconds + span / 2
    offset = max(0.45, span * 0.65)
    offset = min(offset, max(0.08, span - 0.12))
    return start_seconds + offset


def _evenly_spaced_indices(values: list[int], count: int) -> list[int]:
    if count <= 0 or not values:
        return []
    if count >= len(values):
        return values
    if count == 1:
        return [values[len(values) // 2]]
    positions = [round(index * (len(values) - 1) / (count - 1)) for index in range(count)]
    return [values[position] for position in dict.fromkeys(positions)]
