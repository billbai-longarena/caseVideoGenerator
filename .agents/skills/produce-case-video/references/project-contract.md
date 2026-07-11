# Case Project Contract

## Required authored files

- `narration.txt`: Human-readable narration and paragraph-level pauses/cut points.
- `rich_storyboard.json`: Scene, subtitle, layout, keyword, background, and audio declarations.

## Required generated files

- `narration.tts.txt`: Normalized spoken text.
- `narration.tts.plan.txt`: Numbered narration units.
- `narration.timeline.json`: Unit timing and total audio duration.
- `audio/narration_azure.wav`: Default narration asset.

## Required asset directories

- `images/`: Generated or curated visual assets referenced by the storyboard.
- `audio/`: Narration and optional BGM.
- `video/`: Rendered deliverables.

## Optional files

- `image_prompts.json`: Reproducible image-generation prompts.
- `build_storyboard.py`: Case-specific storyboard builder when JSON is generated.
- `tts_overrides.json`: Explicit local pronunciation or synthesis exceptions.
- `sfx/`: Project-specific sound effects.

## Validation invariants

- Timeline unit indices are unique, ordered, and continuous.
- Storyboard scene unit ranges are ordered, non-overlapping, and cover all timeline units.
- Every storyboard audio path exists relative to the project root.
- Every referenced local background image exists under the project root.
- When `image_prompts.json` exists, its prompt files must cover the storyboard scene count, and every primary storyboard background must map to a declared prompt file and an existing image file.
- Primary scene backgrounds should not repeat by default. Reuse is allowed only for an explicit fallback marked on the scene or background cue.
- Generated files are regenerated from their source rather than edited independently.
- Background images used for final delivery are AI-generated or curated narrative illustrations, not PIL/Canvas/SVG/programmatic diagrams, icon sets, flowcharts, dashboards, or placeholders.
- Sales image prompts use the shared blue/yellow watercolor family. Sales-management image prompts use the local warm manager-silhouette motion-graphics family unless the user explicitly approves a different visual reference.
- Generated background prompts exclude readable text, numerals, letters, logos, watermarks, UI screenshots, and source-document screenshots.
