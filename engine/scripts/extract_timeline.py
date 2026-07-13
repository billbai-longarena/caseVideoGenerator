#!/usr/bin/env python3
"""Backfill narration.timeline.json from an existing TTS wav via ffmpeg silencedetect.

The wav was built by concatenating per-unit speech with exact inserted silences
(see narration.tts.plan.txt), so detected gaps map 1:1 to planned pauses.
Fails loudly if the detected gaps cannot be aligned to the plan.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAV = ROOT / "audio" / "narration_cosyvoice.wav"
PLAN = ROOT / "narration.tts.plan.txt"
OUT = ROOT / "narration.timeline.json"

NOISE_DB = "-45dB"
MIN_SILENCE = 0.25
TOLERANCE = 0.1


def parse_plan(path: Path):
    units = []
    pauses = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)\.\s+(.*)$", line.strip())
        if m:
            units.append({"index": int(m.group(1)), "text": m.group(2).strip()})
            continue
        m = re.match(r"^\[pause ([\d.]+)s\]$", line.strip())
        if m:
            pauses.append(float(m.group(1)))
    if len(pauses) != len(units) - 1:
        sys.exit(f"plan mismatch: {len(units)} units but {len(pauses)} pauses")
    return units, pauses


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def detect_silences(path: Path):
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=noise={NOISE_DB}:d={MIN_SILENCE}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    log = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", log)]
    if len(starts) != len(ends):
        sys.exit(f"unpaired silences: {len(starts)} starts vs {len(ends)} ends")
    return list(zip(starts, ends))


def main():
    units, pauses = parse_plan(PLAN)
    duration = probe_duration(WAV)
    gaps = detect_silences(WAV)

    if len(gaps) != len(pauses):
        sys.exit(
            f"detected {len(gaps)} gaps but plan expects {len(pauses)}; "
            f"tune noise/d params or re-run TTS with timeline logging"
        )

    for i, ((_, __), planned) in enumerate(zip(gaps, pauses)):
        detected = gaps[i][1] - gaps[i][0]
        if abs(detected - planned) > TOLERANCE:
            sys.exit(
                f"gap {i + 1}: detected {detected:.3f}s vs planned {planned:.2f}s "
                f"(tolerance {TOLERANCE}s)"
            )

    timeline_units = []
    for i, unit in enumerate(units):
        start = 0.0 if i == 0 else gaps[i - 1][1]
        end = gaps[i][0] if i < len(gaps) else duration
        pause_after = pauses[i] if i < len(pauses) else 0.0
        timeline_units.append({
            "index": unit["index"],
            "text": unit["text"],
            "start": round(start, 3),
            "end": round(end, 3),
            "pauseAfter": pause_after,
        })

    timeline = {
        "audio": "audio/narration_cosyvoice.wav",
        "duration": round(duration, 3),
        "units": timeline_units,
    }
    OUT.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}: {len(timeline_units)} units, "
          f"duration {duration:.3f}s")


if __name__ == "__main__":
    main()
