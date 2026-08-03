#!/usr/bin/env python3
"""Extract scene- and visual-beat-aware QA frames from a rendered case video."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Sample:
    stem: str
    label: str
    seconds: float


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "sample"


def unit_bounds(timeline: dict[str, Any]) -> dict[int, tuple[float, float]]:
    bounds: dict[int, tuple[float, float]] = {}
    for unit in timeline.get("units", []):
        try:
            index = int(unit["index"])
            bounds[index] = (float(unit["start"]), float(unit["end"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not bounds:
        raise SystemExit("timeline has no usable units")
    return bounds


def scene_unit_range(scene: dict[str, Any]) -> tuple[int, int]:
    units = scene.get("units")
    if not isinstance(units, list) or not units:
        raise SystemExit(f"scene {scene.get('id', '<unknown>')} has no units")
    values = [int(value) for value in units]
    return min(values), max(values)


def stable_sample(start: float, end: float, ratio: float = 0.78) -> float:
    duration = max(0.0, end - start)
    if duration <= 0.2:
        return start
    inset = min(0.25, duration * 0.12)
    return min(end - inset, start + duration * ratio)


def scene_samples(
    storyboard: dict[str, Any],
    bounds: dict[int, tuple[float, float]],
    duration: float,
) -> list[Sample]:
    samples = [Sample("00-frame-zero", "frame 0", 0.0)]
    for index, scene in enumerate(storyboard.get("scenes", []), start=1):
        first, last = scene_unit_range(scene)
        start = bounds[first][0]
        end = bounds[last][1]
        scene_id = safe_stem(str(scene.get("id", f"scene-{index:02d}")))
        samples.append(
            Sample(
                stem=f"{index:02d}-{scene_id}",
                label=f"{index:02d} {scene_id} @ {stable_sample(start, end):.1f}s",
                seconds=stable_sample(start, end),
            )
        )
    final_seconds = max(0.0, duration - 0.1)
    samples.append(
        Sample("99-final-frame", f"final @ {final_seconds:.1f}s", final_seconds)
    )
    return samples


def beat_samples(
    storyboard: dict[str, Any],
    bounds: dict[int, tuple[float, float]],
) -> list[Sample]:
    samples: list[Sample] = []
    serial = 1
    for scene_index, scene in enumerate(storyboard.get("scenes", []), start=1):
        first, last = scene_unit_range(scene)
        scene_end = bounds[last][1]
        beats = scene.get("visualBeats")
        if not isinstance(beats, list) or not beats:
            continue
        ordered = sorted(
            (beat for beat in beats if isinstance(beat, dict)),
            key=lambda beat: int(beat.get("atUnit", first)),
        )
        for beat_index, beat in enumerate(ordered):
            at_unit = int(beat.get("atUnit", first))
            start = bounds[at_unit][0]
            if beat_index + 1 < len(ordered):
                next_unit = int(ordered[beat_index + 1].get("atUnit", last))
                end = bounds[next_unit][0]
            else:
                end = scene_end
            beat_id = safe_stem(str(beat.get("id", f"beat-{beat_index + 1:02d}")))
            seconds = stable_sample(start, end)
            samples.append(
                Sample(
                    stem=f"{serial:03d}-s{scene_index:02d}-{beat_id}",
                    label=f"s{scene_index:02d} {beat_id} @ {seconds:.1f}s",
                    seconds=seconds,
                )
            )
            serial += 1
    return samples


def choose_video(project: Path) -> Path:
    candidates = [
        project / "video" / "case_video.mp4",
        project / "video" / "case_video_with_latest_audio.mp4",
        project / "video" / "case_video_video_only.mp4",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(f"no rendered video found under {project / 'video'}")


def probe_video_duration(video: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or f"failed to probe {video}")
    try:
        duration = float(completed.stdout.strip())
    except ValueError as error:
        raise SystemExit(f"ffprobe returned an invalid duration for {video}") from error
    if duration <= 0:
        raise SystemExit(f"ffprobe returned a non-positive duration for {video}")
    return duration


def extract_frame(video: Path, sample: Sample, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{sample.seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not output.is_file():
        raise SystemExit(completed.stderr.strip() or f"failed to extract {sample.label}")


def make_contact_sheet(samples: list[Sample], frames: list[Path], output: Path) -> None:
    columns = 4
    with Image.open(frames[0]) as probe:
        frame_width, frame_height = probe.size
    if frame_height > frame_width:
        tile_width, tile_height = 270, 480
    else:
        tile_width, tile_height = 480, 270
    label_height = 38
    rows = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "#07111f")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=19)
    for index, (sample, frame_path) in enumerate(zip(samples, frames, strict=True)):
        frame = Image.open(frame_path).convert("RGB")
        tile = ImageOps.fit(frame, (tile_width, tile_height), method=Image.Resampling.LANCZOS)
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + label_height)
        sheet.paste(tile, (x, y))
        draw.text((x + 10, y + tile_height + 7), sample.label, fill="#ffffff", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=90)


def render_samples(video: Path, samples: list[Sample], frames_dir: Path, sheet: Path) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale_frame in frames_dir.glob("*.png"):
        stale_frame.unlink()
    frames: list[Path] = []
    for sample in samples:
        frame = frames_dir / f"{sample.stem}.png"
        extract_frame(video, sample, frame)
        frames.append(frame)
    make_contact_sheet(samples, frames, sheet)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-beats", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project = args.project.expanduser().resolve()
    video = args.video.expanduser().resolve() if args.video else choose_video(project)
    if not video.is_file():
        raise SystemExit(f"video not found: {video}")
    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else project / "qa" / "render_qa"
    )
    storyboard = read_json(project / "rich_storyboard.json")
    timeline = read_json(project / "narration.timeline.json")
    bounds = unit_bounds(timeline)
    duration = probe_video_duration(video)

    scenes = scene_samples(storyboard, bounds, duration)
    render_samples(video, scenes, output / "scene_frames", output / "scene_contact_sheet.jpg")
    beat_count = 0
    if not args.skip_beats:
        beats = beat_samples(storyboard, bounds)
        beat_count = len(beats)
        if beats:
            render_samples(video, beats, output / "beat_frames", output / "beat_contact_sheet.jpg")
    print(f"extracted sceneSamples={len(scenes)} beatSamples={beat_count} output={output}")


if __name__ == "__main__":
    main()
