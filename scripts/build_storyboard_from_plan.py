#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def display_text(text: str, replacements: dict[str, str]) -> str:
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def bounded_unit(first: int, last: int, offset: int) -> int:
    return min(last, max(first, first + int(offset)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rich_storyboard.json from a paragraph-based plan.")
    parser.add_argument("project", help="Case-video project directory")
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    timeline = load_json(project / "narration.timeline.json")
    plan = load_json(project / "storyboard_plan.json")
    units = timeline["units"]
    by_paragraph: dict[int, list[dict]] = {}
    for unit in units:
        by_paragraph.setdefault(int(unit["paragraph"]), []).append(unit)

    replacements = plan.get("displayReplacements", {})
    scenes = []
    for position, spec in enumerate(plan["scenes"], start=1):
        paragraph = int(spec.get("paragraph", position))
        paragraph_units = by_paragraph.get(paragraph)
        if not paragraph_units:
            raise SystemExit(f"no timeline units for paragraph {paragraph}")
        first = int(paragraph_units[0]["index"])
        last = int(paragraph_units[-1]["index"])

        props = dict(spec.get("props", {}))
        for key, offset in spec.get("propTimings", {}).items():
            if isinstance(offset, list):
                props[key] = [bounded_unit(first, last, item) for item in offset]
            else:
                props[key] = bounded_unit(first, last, offset)

        keywords = []
        for keyword in spec.get("keywords", []):
            cue = {"text": keyword["text"], "atUnit": bounded_unit(first, last, keyword.get("offset", 0))}
            if keyword.get("sfx"):
                cue["sfx"] = keyword["sfx"]
            keywords.append(cue)

        background = {
            "atUnit": first,
            "transition": spec.get("transition", "wash"),
            "motion": spec.get("motion", "center"),
        }
        if "backgroundVideo" in spec:
            background["video"] = spec["backgroundVideo"]
        else:
            background["image"] = spec["background"]

        scenes.append({
            "id": spec.get("id", f"s{position:02d}"),
            "chapter": spec.get("chapter", f"{position:02d}"),
            "kicker": spec["kicker"],
            "layout": spec["layout"],
            "tone": spec.get("tone", "dark"),
            "units": [first, last],
            "headline": {"text": spec["headline"], "reveal": spec.get("reveal", "perClause"), "accent": spec.get("accent", [])},
            "keywords": keywords,
            "subtitles": [
                {"unit": int(unit["index"]), "text": display_text(unit["text"], replacements)}
                for unit in paragraph_units
            ],
            "backgrounds": [background],
            "props": props,
        })

    storyboard = {
        **plan["project"],
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "audio": "audio/narration_azure.wav",
        "timeline": "narration.timeline.json",
        "duration": timeline["duration"],
        "scenes": scenes,
    }
    output = project / "rich_storyboard.json"
    output.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} scenes={len(scenes)} units={len(units)}")


if __name__ == "__main__":
    main()
