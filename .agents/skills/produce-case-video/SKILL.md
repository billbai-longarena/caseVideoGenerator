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
- **Generate, deliberately reuse, or replenish shared visual assets**: Follow `../../../workflows/reuse-visual-assets.md`. New video work generates fresh project-local backgrounds first; search and checkout background or character pools only for explicit reuse, revision continuity, or intentional callbacks. Treat weak semantic, character, style, or composition fit as a real gap, then return accepted new assets to the appropriate pool after QA.
- **Render or deliver**: Run plan readiness, project validation, typecheck, render readiness, render, ffprobe, and visual QA in that order.
- **Review or audit narration**: Verify `narration.txt` against every item in the writing checklist at the end of `../../../docs/knowledge-base/narration.md`. Do not treat narration review as a surface-level prohibited-pattern scan; the checklist includes structural, beat-level, and theory/teaching checks.
- **Improve the Skill, workflow, validator, or shared engine**: Follow `../../../workflows/improve-production-system.md` and classify the learning before editing a reusable layer.
- **Change reusable pipeline code**: Work in the current engine implementation only after confirming the change benefits multiple case projects.

## Enforce Sources Of Truth

- Use the conditional case-story artifacts required by `references/project-contract.md`; do not turn assumptions into source facts.
- Keep the final human-authored title in `title.txt`; create and review it in the same editorial step as `narration.txt`.
- Keep human-readable speech in `narration.txt`.
- Generate spoken text through the shared TTS normalizer.
- Keep `narration.timeline.json` as the only timing baseline.
- For current projects, keep the schema-v2 `storyboard_plan.json` as the authored visual source of truth. It records the LLM's direction, scene intent, asset casting, composition, camera, timing, layers, chrome, and cover decisions.
- Treat `rich_storyboard.json` as generated render IR when a v2 plan exists. Rebuild it through the deterministic compiler; do not hand-edit it or let the compiler add aesthetic choices. Legacy projects without a v2 plan may continue to use `rich_storyboard.json` until migrated.
- When deliberately reusing shared assets, checkout them into the case project and preserve `asset_pool_usage.json` provenance; never make a storyboard depend directly on the pool's canonical path.
- Generate project-local backgrounds first for new work; keep generated-image prompts and any deliberate checkout provenance as separate declarations, then archive accepted new assets to the appropriate pool after QA.
- Keep generated backgrounds free of clear human faces and story characters: backgrounds carry scene and atmosphere only, and people always appear as separate character-portrait assets, never inside background art.
- Express authored visual timing with narration units, not handwritten seconds.
- Give every newly built video a hook-title cover sourced from `title.txt`, fully visible on frame 0, and ending on a narration unit declared by `cover.throughUnit`.
- Write the visual script before executable beat data: every scene states its dramatic function and `directorialIntent`, and every Visual Beat answers "what visible change does the viewer see and why here". Key numbers, decision networks, and quoted speech use the semantic layer kinds (`counter`, `bar-compare`, `network`, `dialogue`, `annotate`) instead of static text captions. Evidence annotations use only `arrow` or `underline`; `box` and `ring` are disabled because coordinate boxes are too fragile to target reliably.
- Choose `visualMode` by semantic ownership: `layout` for fixed business structures, `editorial` for Visual Beat-led evidence and story layers, and `hybrid` only when the layout remains primary and Visual Beats provide a base image plus optional tint. Do not put panel layers in hybrid scenes or duplicate one fact across the layout and Visual Beats.
- Keep production semantic visual gaps within 12 seconds. A new asset or a story-bearing layer reveal/exit counts; camera, composition, transition, treatment, slot, or timing changes alone do not. Keep callbacks occasional and content-motivated, one active panel per slot, and at most four bars or network nodes per panel.
- Keep reusable implementation out of case directories whenever a shared command or engine change is appropriate.

## Run The Director Loop

For a new visual plan or a material revision, use the LLM as the director before invoking the compiler:

1. Read the title, narration, timeline, case facts, audience, and visual family together. Write one visual thesis plus explicit pacing, density, continuity, and chrome decisions.
2. Give every scene a dramatic function, `directorialIntent`, `visualMode`, and reason for its chosen layout or free-form composition. Do not start from a rotation of available templates.
3. Cast assets from narrative need. Asset count and reuse follow story function, not one-image-per-scene or one-image-per-beat quotas.
4. Author every beat's composition, boxes, camera, treatment, transition, frame counts, layer entrances, and local chrome explicitly in schema v2. Use `director-canvas` when the idea is primarily editorial.
5. Compile the plan deterministically. The compiler may validate, resolve units and paths, and copy declared values; it must not select layouts, cycle styles, add cards, invent beats, or assign motion by index.
6. After real assets exist, run `scripts/case-video intent-frames output/<project>`. Review the actual pixels against every scene's `directorialIntent`; every scene must be represented and review findings must cite the rendered frame IDs.
7. If pixels miss the contract, allow at most one composition-only revision and render the representative frames again. It may change composition, crop, boxes, slots, timing, camera, treatment, transitions, and local chrome, but must preserve facts, copy, layout, asset IDs, scene ranges, and directorial intent.

If the current schema or Remotion primitives cannot express an approved directorial idea, extend the reusable contract and engine first. Do not flatten the idea into the nearest template merely to keep the pipeline moving.

## Apply Production Gates

Use the selected workflow's gates. Do not advance when its current gate fails. At minimum preserve source boundaries, causal consistency, timing integrity, asset validity, render correctness, and delivery QA. Inspect the exact first rendered frame for cover readability and exact annotation frames for evidence targeting. Shared Remotion layout/layer changes must pass the short visual lab before a representative long-video render. The workflow, knowledge base, contract, and validator define the task-specific checks.

Run staged readiness at the earliest cheap boundary. After the storyboard, prompts, and provenance declarations are ready, run `scripts/case-video ready output/<project> --stage plan` before paid image generation; the `images` command also enforces this gate automatically. After real assets exist, run `scripts/case-video ready output/<project> --stage render` before a full or video-only render; both render commands enforce it automatically. Plan readiness rejects a missing or mismatched `title.txt`, cyclic or concentrated scheduling, stale derived data, undeclared assets, weak visual intent, and invalid cover intent. Render readiness additionally runs strict project validation, checks actual portrait pixels/provenance/style, and renders the exact frame-0 cover plus its transparent proof overlay to verify center-crop geometry and scrim size. Do not bypass readiness for production delivery; `CASE_VIDEO_SKIP_READINESS=1` is only for focused pipeline debugging.

After changing scene boundaries, a storyboard generator, or Visual Beat scheduling, run the render-free `build` and `evaluate` commands from `references/commands.md` with the existing timeline and assets before regenerating audio, images, or a full video. Treat stale derived storyboards and cyclic scheduling as architecture failures; do not improve a score with decorative layers, repeated text, or disabled annotation shapes.

Run project validation after any storyboard or image-asset change. It is the guardrail that rejects QA/contact-sheet/overview images being referenced as final backgrounds or character assets.

## Preserve Creative Freedom

- Apply current defaults and methods from `../../../docs/knowledge-base/`; do not duplicate their detailed values here.
- Choose `layout`, `editorial`, or `hybrid` scene by scene according to the communication need. Templates are optional capabilities: use a semantic layout only when its structure is the clearest expression of the scene; use `director-canvas` plus explicit boxes/layers for authored editorial composition.
- Treat pacing ranges and composition patterns as planning aids unless the contract or validator marks a rule as invariant.
- Do not encode a fixed shot count, cut interval, beat count, asset quota, narrative twist, case outcome, template rotation, or single-case style recipe in this Skill.
- Do not reward visual quantity by itself. Repeated labels, generic cards, camera-only changes, and modulo-selected variants are not evidence of direction or semantic progress.

## Improve Deliberately

After production or QA, classify each reusable finding before changing the system:

- case-specific choice → `output/<project>/`
- reusable method → `docs/knowledge-base/`
- ordered step or quality gate → `workflows/`
- deterministic invariant → schema, builder, validator, and tests
- task routing or cross-stage guardrail → this Skill

Promote findings to the Skill only when they are stable across tasks and materially change routing or safety. Use `../../../workflows/improve-production-system.md` for evidence, regression checks, and rollback criteria.

## Compose Covers For Center Crops

- Place the complete essential cover-copy group—kicker, title, and required subtitle—at the frame's geometric center, use centered text alignment, and keep it inside the centered crop-safe area. Do not anchor essential cover text to the left or right.
- If contrast requires a black scrim, fit it to the text block plus modest padding and keep it translucent. Do not use a full-frame, full-height, or wide black panel; preserve clearly visible background around all four sides.
- QA exact frame 0 at full 16:9 and in a centered 1:1 crop. Reject the cover if essential text is clipped or off-center, or if the scrim visually dominates the background.
