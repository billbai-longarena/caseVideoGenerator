---
name: produce-case-video
description: Model, produce, revise, render, and quality-check Chinese sales and sales-management case stories and videos in this repository. Use for case-story generation, narration and TTS, unit-anchored storyboards and Visual Beats, generated assets, Remotion rendering, delivery QA, or reusable production-system improvements.
---

# Produce Case Video

## Start

1. Read `../../../docs/README.md` for the knowledge map.
2. Read the workflow matching the task in `../../../workflows/`.
3. Read `references/project-contract.md` before creating or validating project artifacts.
4. Read `references/commands.md` before TTS, rendering, muxing, or QA.
5. Treat `output/<project>/` as case data. The shared engine lives in `engine/`; change it only for reusable behavior.

## Route The Task

- **Generate or reconstruct a case story**: Follow `../../../workflows/generate-case-story.md` and its linked case-model knowledge.
- **Create a complete video**: Follow `../../../workflows/new-case-video.md`; run the case-story workflow first when the story is not already approved.
- **Change narration or timing**: Follow the audio path in `../../../workflows/revise-video.md`; regenerate the timeline before changing visual timing.
- **Change storyboard or visuals**: Follow the visual path in `../../../workflows/revise-video.md`; preserve narration unit anchors.
- **Find, reuse, or replenish shared visual assets**: Follow `../../../workflows/reuse-visual-assets.md`; search and visually review background and character pools before generating gaps. Treat weak semantic, character, style, or composition fit as a real gap, then return accepted new assets to the appropriate pool after QA.
- **Render or deliver**: Run project validation, typecheck, render, ffprobe, and visual QA in that order.
- **Improve the Skill, workflow, validator, or shared engine**: Follow `../../../workflows/improve-production-system.md` and classify the learning before editing a reusable layer.
- **Change reusable pipeline code**: Work in the current engine implementation only after confirming the change benefits multiple case projects.

## Enforce Sources Of Truth

- Use the conditional case-story artifacts required by `references/project-contract.md`; do not turn assumptions into source facts.
- Keep human-readable speech in `narration.txt`.
- Generate spoken text through the shared TTS normalizer.
- Keep `narration.timeline.json` as the only timing baseline.
- Keep `rich_storyboard.json` as the source of truth for scenes, subtitles, layouts, backgrounds, assets, and Visual Beats.
- Checkout shared assets into the case project and preserve `asset_pool_usage.json` provenance; never make a storyboard depend directly on the pool's canonical path.
- Use the shared pool before generating missing backgrounds, while keeping generated-image prompts and checked-out provenance as separate declarations.
- Express authored visual timing with narration units, not handwritten seconds.
- Write the visual script before the storyboard data: every Visual Beat answers "what visible change does the viewer see", and key numbers, decision networks, and quoted speech use the semantic layer kinds (`counter`, `bar-compare`, `network`, `dialogue`, `annotate`) instead of static text captions.
- Keep reusable implementation out of case directories whenever a shared command or engine change is appropriate.

## Apply Production Gates

Use the selected workflow's gates. Do not advance when its current gate fails. At minimum preserve source boundaries, causal consistency, timing integrity, asset validity, render correctness, and delivery QA. The workflow, knowledge base, contract, and validator define the task-specific checks.

## Preserve Creative Freedom

- Apply current defaults and methods from `../../../docs/knowledge-base/`; do not duplicate their detailed values here.
- Choose `layout`, `editorial`, or `hybrid` scene by scene according to the communication need.
- Treat pacing ranges and composition patterns as planning aids unless the contract or validator marks a rule as invariant.
- Do not encode a fixed shot count, cut interval, narrative twist, case outcome, or single-case style recipe in this Skill.

## Improve Deliberately

After production or QA, classify each reusable finding before changing the system:

- case-specific choice → `output/<project>/`
- reusable method → `docs/knowledge-base/`
- ordered step or quality gate → `workflows/`
- deterministic invariant → schema, builder, validator, and tests
- task routing or cross-stage guardrail → this Skill

Promote findings to the Skill only when they are stable across tasks and materially change routing or safety. Use `../../../workflows/improve-production-system.md` for evidence, regression checks, and rollback criteria.
