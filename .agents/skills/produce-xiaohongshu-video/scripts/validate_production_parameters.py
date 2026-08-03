#!/usr/bin/env python3
"""Validate a Xiaohongshu production_parameters.txt handoff."""

from __future__ import annotations

import argparse
from pathlib import Path


ALLOWED_STATUSES = {"DRAFT", "WAITING_FOR_APPROVAL", "APPROVED", "SUPERSEDED"}

REQUIRED = {
    "DOCUMENT": [
        "DOCUMENT_TYPE", "SCHEMA_VERSION", "APPROVAL_STATUS", "PROJECT_DIR",
        "EPISODE_ID", "SOURCE_FILES", "PLANNING_SCOPE",
    ],
    "APPROVAL": [
        "USER_APPROVAL_REQUIRED", "APPROVED_AT", "APPROVED_BY",
        "PENDING_DECISIONS", "LOCKED_AFTER_APPROVAL",
    ],
    "MATRIX": [
        "ROLE_CODE", "STAGE_CODE", "CHALLENGE_CODE", "THEORY_CODES",
        "ARC_CODE", "INDUSTRY", "PROTAGONIST_AGE", "ANTI_REPETITION_RESULT",
    ],
    "TITLE_AND_HOOK": [
        "SOURCE_TITLE", "PRIMARY_TITLE", "ALTERNATE_TITLES", "COVER_TITLE",
        "HOOK_EVENT", "HOOK_DIRECTION",
    ],
    "PEOPLE_AND_EVENT": [
        "PERSON_1", "PERSON_2", "PERSON_3", "CORE_EVENT_CHAIN",
        "TURNING_BEHAVIOR", "RESULT_BEHAVIOR",
    ],
    "THEORY_AND_CTA": [
        "THEORY_GOLD_SENTENCE", "THEORY_FRAME_DIRECTION", "CLOSING_CTA",
    ],
    "NARRATION": [
        "LANGUAGE", "TARGET_CHARACTERS", "TARGET_DURATION", "STRUCTURE",
        "FORBIDDEN_PATTERNS",
    ],
    "VIDEO": [
        "CANVAS", "FPS", "VISUAL_MODE", "SCENE_TARGET", "BEAT_TARGET",
        "BEAT_DURATION", "COVER_MAX_DURATION", "SUBTITLE_LABEL",
    ],
    "VISUALS": [
        "VISUAL_FAMILY", "PALETTE", "STYLE_DIRECTION", "BACKGROUND_SIZE",
        "BACKGROUND_COUNT", "PORTRAIT_SIZE", "PORTRAIT_COUNT",
        "PORTRAIT_CONTRACT", "TEXT_SURFACE", "TREATMENT_COLOR",
        "ASSET_FORBIDDENS",
    ],
    "TTS": [
        "ENGINE", "VOICE", "PROFILE", "RATE", "PITCH", "PARAGRAPH_GAP",
        "VOICE_MODE",
    ],
    "EXECUTION_HANDOFF": [
        "EXECUTION_BLOCKED_UNTIL", "EXECUTOR_MUST_READ",
        "EXECUTOR_MUST_PRESERVE", "STOP_AND_ESCALATE_IF", "DO_NOT_GENERATE_YET",
    ],
}


def parse(path: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    sections: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    current: str | None = None

    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            if current in sections:
                errors.append(f"line {line_number}: duplicate section [{current}]")
            sections.setdefault(current, {})
            continue
        if current is None or ":" not in line:
            errors.append(f"line {line_number}: expected [SECTION] or KEY: value")
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key in sections[current]:
            errors.append(f"line {line_number}: duplicate key {current}.{key}")
        sections[current][key] = value

    return sections, errors


def validate(path: Path, require_approved: bool) -> list[str]:
    if not path.is_file():
        return [f"file not found: {path}"]

    sections, errors = parse(path)
    for section, keys in REQUIRED.items():
        if section not in sections:
            errors.append(f"missing section [{section}]")
            continue
        for key in keys:
            if key not in sections[section]:
                errors.append(f"missing key {section}.{key}")
            elif not sections[section][key]:
                errors.append(f"empty value {section}.{key}")

    document = sections.get("DOCUMENT", {})
    status = document.get("APPROVAL_STATUS", "")
    if status not in ALLOWED_STATUSES:
        errors.append(f"invalid APPROVAL_STATUS: {status!r}")
    if document.get("DOCUMENT_TYPE") != "XIAOHONGSHU_PRODUCTION_PARAMETERS":
        errors.append("DOCUMENT_TYPE must be XIAOHONGSHU_PRODUCTION_PARAMETERS")
    if document.get("SCHEMA_VERSION") != "1":
        errors.append("SCHEMA_VERSION must be 1")

    if require_approved:
        if status != "APPROVED":
            errors.append(f"execution blocked: APPROVAL_STATUS is {status!r}, expected 'APPROVED'")
        pending_lines = [
            f"{section}.{key}"
            for section, values in sections.items()
            for key, value in values.items()
            if "PENDING" in value.upper()
        ]
        if pending_lines:
            errors.append("execution blocked: unresolved PENDING values at " + ", ".join(pending_lines))
        title = sections.get("TITLE_AND_HOOK", {}).get("PRIMARY_TITLE")
        cover = sections.get("TITLE_AND_HOOK", {}).get("COVER_TITLE")
        if title and cover and title != cover:
            errors.append("PRIMARY_TITLE and COVER_TITLE must match after approval")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()

    errors = validate(args.path, args.require_approved)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    mode = "approved execution" if args.require_approved else "planning structure"
    print(f"PASS: {args.path} satisfies the {mode} contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
