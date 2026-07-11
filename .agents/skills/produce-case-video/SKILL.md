---
name: produce-case-video
description: Produce, revise, render, and quality-check Chinese case-story videos in this repository. Use when turning case source material into narration, Azure Speech TTS, narration.timeline.json, rich_storyboard.json, generated visuals, Remotion video, or ffmpeg QA; also use when repairing narration, timing, storyboard, assets, or final delivery for an existing case-video project.
---

# Produce Case Video

## Start

1. Read `../../../docs/README.md` for the knowledge map.
2. Read the workflow matching the task in `../../../workflows/`.
3. Treat the target directory under `output/` as case data, not reusable engine code.
4. Use `../../../scripts/case-video` instead of memorizing paths inside the Budweiser project.

Read `references/project-contract.md` before creating or validating a project. Read `references/commands.md` before running TTS, rendering, muxing, or QA commands.

## Route The Task

- **Create a complete video**: Follow `../../../workflows/new-case-video.md` from source review through delivery.
- **Change narration or timing**: Follow the audio path in `../../../workflows/revise-video.md`; regenerate the timeline before changing visual timing.
- **Change storyboard or visuals**: Follow the visual path in `../../../workflows/revise-video.md`; preserve narration unit anchors.
- **Render or deliver**: Run project validation, typecheck, render, ffprobe, and visual QA in that order.
- **Change reusable pipeline code**: Work in the current engine implementation only after confirming the change benefits multiple case projects.

## Enforce Sources Of Truth

- Keep human-readable speech in `narration.txt`.
- Generate spoken text through the shared TTS normalizer; do not hand-maintain `narration.tts.txt` as an independent source.
- Keep `narration.timeline.json` as the only timing baseline.
- Keep `rich_storyboard.json` as the only source for scenes, subtitles, keyword cues, layouts, and backgrounds.
- Express timing with narration units such as `units` and `atUnit`; do not introduce handwritten seconds when unit timing exists.
- Keep reusable implementation out of case directories whenever a shared command or engine change is appropriate.

## Apply Production Gates

Stop and fix the current phase before continuing when a gate fails:

1. **Source gate**: Confirm usage boundaries and avoid sending restricted source text to external providers.
2. **Narration gate**: Confirm target duration, natural spoken Chinese, fixed column opener/closer when applicable, and prohibited contrast-pattern removal.
3. **TTS gate**: Confirm normalized numbers/acronyms, female single-voice profile, timeline generation, and listening quality.
4. **Storyboard gate**: Confirm continuous unit coverage, semantic reveal timing, valid layouts, and subtitle safety.
5. **Asset gate**: Confirm story-specific prompts, the approved blue/yellow watercolor family for sales cases and the local warm manager-silhouette family for sales-management cases, no unwanted color/style drift, no logos/readable text/numerals/letters/watermarks, and no programmatic/diagram/placeholder backgrounds.
6. **Render gate**: Confirm project validation and Remotion typecheck before a full render.
7. **Delivery gate**: Confirm video/audio streams, dimensions, frame rate, duration, contact sheet, key frames, and spoken numeric accuracy.

## Preserve Current Defaults

- Use a 4–7 minute duration when the user does not specify one.
- Use the `销售不复杂` opener, closer, brand, and subtitle label for sales-case videos unless told otherwise.
- Use Azure Speech with the approved Dragon HD female single-voice broadcast profile by default.
- Use male/female alternation only when the user explicitly requests it.
- Use Remotion for motion graphics and ffmpeg/ffprobe for muxing and QA.
- Avoid the Chinese rhetorical pattern `不是……而是……` and close variants.
- Use AI-generated or curated narrative illustration backgrounds for final delivery: sales cases use the approved blue/yellow watercolor family, while sales-management cases use the local warm manager-silhouette motion-graphics family unless the user approves another reference. Keep storyboard scene count, prompt files, primary background refs, and actual image files aligned; reuse prior images only as an explicit fallback. If Azure image generation fails, fix the image configuration or stop; do not substitute PIL/Canvas/SVG/programmatic diagrams or icon-style placeholders.

## Record Durable Changes

Update the appropriate file under `../../../docs/knowledge-base/` when a reusable rule changes. Update a workflow only when task order or a gate changes. Keep case-specific observations inside the relevant `output/<project>/` directory.
