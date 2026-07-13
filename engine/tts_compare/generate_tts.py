#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
AZURE_SCRIPT = SCRIPT_ROOT / "generate_azure_full.py"
AZURE_BROADCAST_SCRIPT = SCRIPT_ROOT / "generate_dragon_broadcast.py"
COSYVOICE_SCRIPT = SCRIPT_ROOT / "generate_cosy_full.py"

ENGINE_ALIASES = {
    "azure": "azure",
    "azure-speech": "azure",
    "speech": "azure",
    "cosy": "cosyvoice",
    "cosyvoice": "cosyvoice",
}


def normalize_engine(value: str) -> str:
    engine = ENGINE_ALIASES.get(value.strip().lower())
    if not engine:
        expected = ", ".join(sorted(ENGINE_ALIASES))
        raise argparse.ArgumentTypeError(f"Unsupported TTS engine '{value}'. Expected one of: {expected}")
    return engine


def add_project_arg(cmd: list[str], project: str | None) -> None:
    if project:
        cmd.extend(["--project", str(Path(project).expanduser())])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate narration audio/timeline with selectable TTS engine.",
    )
    parser.add_argument(
        "--engine",
        default=os.environ.get("CASEVIDEO_TTS_ENGINE") or os.environ.get("TTS_ENGINE") or "azure",
        type=normalize_engine,
        help="TTS engine: azure or cosyvoice. Defaults to azure.",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("VIDEO_PROJECT_DIR"),
        help="Project directory containing narration.txt. Defaults to VIDEO_PROJECT_DIR or the engine root.",
    )
    parser.add_argument(
        "--profile",
        default=os.environ.get("AZURE_TTS_PROFILE", "dragon-broadcast"),
        choices=("dragon-broadcast", "legacy-sentence"),
        help="Azure production profile. Defaults to the approved Dragon broadcast profile.",
    )
    parser.add_argument(
        "--gender",
        help="Azure starting voice gender: female/male, 女声/男声. Paragraph alternation remains enabled.",
    )
    parser.add_argument(
        "--voice",
        help="Full Azure primary voice name. Uses one voice unless --alternate-voice is also provided.",
    )
    parser.add_argument(
        "--alternate-voice",
        help="Second Azure voice for even-numbered paragraphs. Applies only to --engine azure.",
    )
    parser.add_argument(
        "--single-voice",
        action="store_true",
        help="Disable Azure's default male/female paragraph alternation.",
    )
    parser.add_argument(
        "--rate",
        help="Azure SSML prosody rate, for example +4%%, 0%%, or -4%%.",
    )
    parser.add_argument(
        "--mode",
        help="Azure synthesis mode: sentence (default), continuous, or segmented/legacy. Applies only to --engine azure.",
    )
    parser.add_argument(
        "--only",
        help="Regenerate only selected Azure sentence cache slots, for example 3 or 3,5-7.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all Azure sentence cache slots even when cached metadata matches.",
    )
    parser.add_argument(
        "--speaker",
        help="CosyVoice speaker name. Applies only to --engine cosyvoice.",
    )
    parser.add_argument(
        "--speed",
        help="CosyVoice speed value. Applies only to --engine cosyvoice.",
    )
    args = parser.parse_args()

    env = os.environ.copy()
    if args.engine == "azure":
        use_broadcast = (
            args.profile == "dragon-broadcast"
            and not args.voice
            and not args.alternate_voice
            and not args.mode
            and not args.only
        )
        cmd = [sys.executable, str(AZURE_BROADCAST_SCRIPT if use_broadcast else AZURE_SCRIPT)]
        add_project_arg(cmd, args.project)
        if use_broadcast:
            if args.gender:
                cmd.extend(["--gender", args.gender])
            if args.single_voice:
                cmd.append("--single-voice")
            if args.rate:
                cmd.extend(["--male-rate", args.rate, "--female-rate", args.rate])
            print(f"tts_engine=azure profile=dragon-broadcast project={args.project or '<default>'}", flush=True)
        elif args.voice:
            cmd.extend(["--voice", args.voice])
        elif args.gender:
            cmd.extend(["--gender", args.gender])
        if args.alternate_voice:
            cmd.extend(["--alternate-voice", args.alternate_voice])
        if args.single_voice:
            cmd.append("--single-voice")
        if args.rate and not use_broadcast:
            cmd.extend(["--rate", args.rate])
        if args.mode:
            cmd.extend(["--mode", args.mode])
        if args.only:
            cmd.extend(["--only", args.only])
        if args.force:
            cmd.append("--force")
        if not use_broadcast:
            print(f"tts_engine=azure profile=legacy-sentence project={args.project or '<default>'}", flush=True)
    else:
        cmd = [sys.executable, str(COSYVOICE_SCRIPT)]
        add_project_arg(cmd, args.project)
        if args.speaker:
            env["COSYVOICE_SPEAKER"] = args.speaker
        if args.speed:
            env["COSYVOICE_SPEED"] = args.speed
        print(f"tts_engine=cosyvoice project={args.project or '<default>'}", flush=True)

    subprocess.run(cmd, env=env, check=True)


if __name__ == "__main__":
    main()
