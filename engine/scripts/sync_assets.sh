#!/usr/bin/env bash
# Sync single-source-of-truth data + assets into the Remotion project.
set -euo pipefail

ENGINE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${VIDEO_PROJECT_DIR:-}" ]; then
  echo "VIDEO_PROJECT_DIR must point to a case project (engine holds no case data)" >&2
  exit 1
fi
ROOT="$(cd "$VIDEO_PROJECT_DIR" && pwd)"
REMOTION="$ENGINE_ROOT/remotion"

mkdir -p "$REMOTION/src/data/generated" "$REMOTION/public/audio" "$REMOTION/public/images" "$REMOTION/public/videos" "$REMOTION/public/sfx"

cp "$ROOT/rich_storyboard.json" "$REMOTION/src/data/generated/rich_storyboard.json"
cp "$ROOT/narration.timeline.json" "$REMOTION/src/data/generated/narration.timeline.json"

if [ -d "$ROOT/images" ]; then
  rsync -a --delete "$ROOT/images/" "$REMOTION/public/images/"
else
  rm -rf "$REMOTION/public/images"
  mkdir -p "$REMOTION/public/images"
fi

if [ -d "$ROOT/videos" ]; then
  rsync -a --delete "$ROOT/videos/" "$REMOTION/public/videos/"
else
  rm -rf "$REMOTION/public/videos"
  mkdir -p "$REMOTION/public/videos"
fi

AUDIO_PATH="$(python3 - "$ROOT/rich_storyboard.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
print(data.get("audio", "audio/narration_azure.wav"))
PY
)"
mkdir -p "$REMOTION/public/$(dirname "$AUDIO_PATH")"
cp "$ROOT/$AUDIO_PATH" "$REMOTION/public/$AUDIO_PATH"

HAS_BGM=false
if [ -f "$ROOT/audio/bgm_corporate.mp3" ]; then
  cp "$ROOT/audio/bgm_corporate.mp3" "$REMOTION/public/audio/bgm_corporate.mp3"
  HAS_BGM=true
fi

HAS_SFX=false
if [ -d "$ROOT/sfx" ] && [ -n "$(ls -A "$ROOT/sfx" 2>/dev/null)" ]; then
  rsync -a "$ROOT/sfx/" "$REMOTION/public/sfx/"
  HAS_SFX=true
fi

printf '{\n  "hasBgm": %s,\n  "hasSfx": %s\n}\n' "$HAS_BGM" "$HAS_SFX" \
  > "$REMOTION/src/data/generated/assets.json"

echo "synced project=$ROOT -> remotion/ (bgm=$HAS_BGM sfx=$HAS_SFX)"
