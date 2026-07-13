#!/usr/bin/env bash
# Replace the audio track on an existing rendered video by stream-copying video.
# This is the fast path after sentence-level TTS fixes when the picture layer
# has not changed.
set -euo pipefail

ENGINE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${VIDEO_PROJECT_DIR:-}" ]; then
  echo "VIDEO_PROJECT_DIR must point to a case project (engine holds no case data)" >&2
  exit 1
fi
PROJECT_ROOT="$VIDEO_PROJECT_DIR"
ROOT="$(cd "$PROJECT_ROOT" && pwd)"

VIDEO_IN="${VIDEO_LAYER:-$ROOT/video/case_video_video_only.mp4}"
OUTPUT="${VIDEO_OUTPUT:-$ROOT/video/case_video_with_latest_audio.mp4}"
AUDIO_BITRATE="${AUDIO_BITRATE:-192k}"

AUDIO_PATH="${AUDIO_PATH:-$(python3 - "$ROOT/rich_storyboard.json" "$ROOT/narration.timeline.json" <<'PY'
import json
import sys
from pathlib import Path

storyboard_path = Path(sys.argv[1])
timeline_path = Path(sys.argv[2])

audio = None
if timeline_path.exists():
    with timeline_path.open(encoding="utf-8") as fh:
        audio = json.load(fh).get("audio")
if not audio and storyboard_path.exists():
    with storyboard_path.open(encoding="utf-8") as fh:
        audio = json.load(fh).get("audio")
print(audio or "audio/narration_azure.wav")
PY
)}"

if [[ "$AUDIO_PATH" = /* ]]; then
  AUDIO_IN="$AUDIO_PATH"
else
  AUDIO_IN="$ROOT/$AUDIO_PATH"
fi

if [ ! -f "$VIDEO_IN" ]; then
  echo "missing video layer: $VIDEO_IN" >&2
  echo "render it first with: cd $ENGINE_ROOT/remotion && npm run render:video" >&2
  exit 1
fi

if [ ! -f "$AUDIO_IN" ]; then
  echo "missing audio: $AUDIO_IN" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

ffmpeg -hide_banner -y \
  -i "$VIDEO_IN" \
  -i "$AUDIO_IN" \
  -map 0:v:0 \
  -map 1:a:0 \
  -c:v copy \
  -c:a aac \
  -b:a "$AUDIO_BITRATE" \
  -shortest \
  "$OUTPUT"

ffprobe -v error \
  -show_entries stream=codec_type,width,height,r_frame_rate:format=duration \
  -of compact=p=0:nk=1 \
  "$OUTPUT"

echo "muxed video=$VIDEO_IN audio=$AUDIO_IN output=$OUTPUT"
