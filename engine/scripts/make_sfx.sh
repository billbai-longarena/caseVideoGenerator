#!/usr/bin/env bash
# Synthesize placeholder SFX with ffmpeg (no licensing risk; swap for CC0 assets later).
set -euo pipefail

ENGINE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${VIDEO_PROJECT_DIR:-}" ]; then
  echo "VIDEO_PROJECT_DIR must point to a case project (engine holds no case data)" >&2
  exit 1
fi
PROJECT_ROOT="$VIDEO_PROJECT_DIR"
ROOT="$(cd "$PROJECT_ROOT" && pwd)"
OUT="$ROOT/sfx"
mkdir -p "$OUT"

# pop: short decaying blip, 880Hz body + 440Hz undertone
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=880:duration=0.12" \
  -f lavfi -i "sine=frequency=440:duration=0.12" \
  -filter_complex "[0:a][1:a]amix=inputs=2:weights=1 0.5,volume='exp(-22*t)':eval=frame,afade=t=in:d=0.004" \
  "$OUT/pop.wav"

# whoosh: pink-noise swell through a bandpass
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "anoisesrc=color=pink:duration=0.5:seed=7" \
  -af "bandpass=f=900:w=600,volume='min(t*8,1)*(1-min(max(t-0.25,0)*4,1))':eval=frame" \
  "$OUT/whoosh.wav"

# stamp: low thud, hard decay
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=120:duration=0.16" \
  -af "volume='exp(-16*t)':eval=frame,afade=t=in:d=0.003" \
  "$OUT/stamp.wav"

# flash: descending shimmer sweep 1600->400Hz
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "sine=frequency=1600:duration=0.3" \
  -af "vibrato=f=8:d=0.4,volume='0.8*exp(-8*t)':eval=frame,afade=t=in:d=0.005" \
  "$OUT/flash.wav"

echo "wrote $(ls "$OUT" | wc -l | tr -d ' ') sfx files to $OUT"
