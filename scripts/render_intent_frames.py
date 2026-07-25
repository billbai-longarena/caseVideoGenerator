#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.app.services.intent_frames import select_intent_frames  # noqa: E402


def read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def render(project: Path, *, max_frames: int, composition: str) -> dict[str, Any]:
    storyboard = read_object(project / "rich_storyboard.json")
    timeline = read_object(project / "narration.timeline.json")
    frames = select_intent_frames(storyboard, timeline, max_frames=max_frames)
    output_root = project / "qa" / "intent-frames"
    output_root.mkdir(parents=True, exist_ok=True)
    for old_frame in output_root.glob("frame-*.png"):
        old_frame.unlink()

    remotion_root = REPO_ROOT / "engine" / "remotion"
    remotion_bin = remotion_root / "node_modules" / ".bin" / "remotion"
    if not remotion_bin.is_file():
        raise SystemExit(f"Remotion CLI is missing: {remotion_bin}")
    env = os.environ.copy()
    env["VIDEO_PROJECT_DIR"] = str(project)
    subprocess.run(
        ["bash", str(REPO_ROOT / "engine" / "scripts" / "sync_assets.sh")],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    for record in frames:
        destination = output_root / record["file"]
        subprocess.run(
            [
                str(remotion_bin),
                "still",
                "src/index.ts",
                composition,
                str(destination),
                f"--frame={record['frame']}",
                "--image-format=png",
                "--overwrite",
            ],
            cwd=remotion_root,
            env=env,
            check=True,
        )
        if not destination.is_file() or destination.stat().st_size == 0:
            raise SystemExit(f"Remotion did not produce {destination}")

    manifest = {
        "version": "1",
        "composition": composition,
        "fps": int(storyboard.get("fps", 30)),
        "frame_count": len(frames),
        "frames": frames,
    }
    write_json(output_root / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Render scene/beat frames for intent-to-pixel review.")
    parser.add_argument("project", type=Path)
    parser.add_argument("--max-frames", type=int, default=24)
    parser.add_argument("--composition", default="CaseVideoIntentReview")
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    if not project.is_dir():
        parser.error(f"project directory not found: {project}")
    if args.max_frames < 1:
        parser.error("--max-frames must be positive")
    manifest = render(project, max_frames=args.max_frames, composition=args.composition)
    print(
        f"rendered {manifest['frame_count']} intent frames -> "
        f"{project / 'qa' / 'intent-frames' / 'manifest.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
