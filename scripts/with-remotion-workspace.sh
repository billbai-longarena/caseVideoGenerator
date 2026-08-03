#!/usr/bin/env bash
set -euo pipefail

# Run a Remotion-facing case-video command in a disposable engine workspace.
# The canonical engine keeps source code and node_modules; generated JSON and
# project media are written only into this job-local copy.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ENGINE="${CASE_VIDEO_ENGINE_SOURCE_ROOT:-$REPO_ROOT/engine}"
WORKSPACE_PARENT="${CASE_VIDEO_WORKSPACE_ROOT:-${TMPDIR:-/tmp}}"

if [[ ! -d "$SOURCE_ENGINE/remotion" || ! -f "$SOURCE_ENGINE/remotion/package.json" ]]; then
  echo "Remotion engine is incomplete: $SOURCE_ENGINE" >&2
  exit 1
fi
if [[ ! -d "$SOURCE_ENGINE/remotion/node_modules" ]]; then
  echo "Remotion dependencies are missing: $SOURCE_ENGINE/remotion/node_modules" >&2
  exit 1
fi

mkdir -p "$WORKSPACE_PARENT"
WORKSPACE="$(mktemp -d "$WORKSPACE_PARENT/case-video-remotion.XXXXXX")"
cleanup() {
  rm -rf "$WORKSPACE"
}
trap cleanup EXIT INT TERM

mkdir -p "$WORKSPACE/engine"
rsync -a --delete \
  --exclude 'remotion/node_modules' \
  --exclude 'remotion/public' \
  --exclude 'remotion/src/data/generated' \
  --exclude 'remotion/out' \
  --exclude 'remotion/output' \
  --exclude 'remotion/.cache' \
  --exclude 'remotion/.case-video.lock' \
  --exclude '*/__pycache__' \
  --exclude '*.pyc' \
  "$SOURCE_ENGINE/" "$WORKSPACE/engine/"

mkdir -p "$WORKSPACE/engine/remotion/public" \
  "$WORKSPACE/engine/remotion/src/data/generated"
ln -s "$SOURCE_ENGINE/remotion/node_modules" "$WORKSPACE/engine/remotion/node_modules"

export CASE_VIDEO_ENGINE_ROOT="$WORKSPACE/engine"
export CASE_VIDEO_ISOLATED_WORKSPACE=1

"$REPO_ROOT/scripts/case-video" "$@"
