---
name: produce-vertical-video
description: Produce, revise, render, and quality-check vertical 9:16 (1080x1920) mobile case-story videos in this repository. Use when the user asks for phone/mobile/vertical video, 抖音/视频号/Shorts/Reels output, or any 9:16 deliverable. Shares the narration, TTS, storyboard-plan, asset, and QA contracts with produce-case-video; this skill adds the vertical canvas, mobile layout, and vertical image rules.
---

# Produce Vertical Video

## Start

1. Read `../../../docs/knowledge-base/vertical-mobile-video.md` for the canvas contract and mobile best-practice values.
2. Read `../../../workflows/new-vertical-video.md` for the ordered stages and gates.
3. Read `../produce-case-video/references/project-contract.md` and `../produce-case-video/references/commands.md`; every contract there still applies unless the vertical knowledge base overrides it.
4. Only use this skill when the user explicitly wants vertical/mobile output. Landscape 1920x1080 remains the default.

## Vertical Invariants

- Declare `"canvas": {"width": 1080, "height": 1920}` at the top level of the schema-v2 `storyboard_plan.json`. The compiler rejects other sizes; omitting it means landscape.
- Every scene is `visualMode: editorial`. Legacy template layouts are 16:9-only and the validator rejects them on a vertical canvas. Compose with Visual Beat compositions, slots, and normalized `box` coordinates.
- Keep essential content inside the mobile safe area: platform overlay UI (视频号/小红书 top tabs, bottom avatar/description/action rail) covers the edges, so nothing critical above y 320 or below y 1240; the persistent brand chip sits at `top: 310` and the subtitle bar floats at `bottom: 400`, clear of platform chrome.
- The vertical canvas never renders the top-right ChapterBadge: the corner sits under platform UI and `chapter` words are director-facing labels. Write every on-screen label (`chapter`, `kicker`, cover text) for the audience — internal production terms such as `钩子`/`悬念`/`铺垫`/`反转`/`高潮`/`收尾` belong in `dramaticFunction`/`directorialIntent`, never in rendered text. Note `chapter` still flashes in `chapter-circle` transitions on vertical and in the landscape badge, so the wording rule applies to all canvases.
- Prefer image-top/text-bottom compositions for framed/card media (`portrait-left`/`portrait-right` map to a top 56% image on vertical canvases). Background-like `baseAsset` images (`bg-*`, `*-bg-*`, `background-*`) stay full-canvas; never shrink them into an upper band that stacks with the compatibility background track. Use full-width stacked text lanes and one subject per frame; phones cannot carry multi-subject wide scenes.
- Use large type: the engine's vertical text scale starts captions at 42px and cover titles at up to 100px. Keep on-screen text short enough to stay within two lines per card.
- Keep beats to 4-8 seconds; the 12-second semantic-gap ceiling still applies.
- The column label (`subtitleLabel`) stays on one line in the stacked vertical subtitle bar, same as landscape.

## Validator Boundaries That Bite In Practice

- Opaque text surfaces (`paper`/`accent`/`solid`) must bind an explicit normalized `box`; slot-bound opaque cards are rejected. Keep the layer's `slot` alongside its `box`: the overlap checker reasons about slots while the renderer prefers the box.
- The validator whitelists differ from the raw schema: beat `composition` accepts only `full-bleed`, `portrait-left`, `portrait-right`, `split`, `triptych`, `document-focus`, `evidence-collage` (no `custom`); beat `purpose` accepts only `establish`, `identify`, `evidence`, `explain`, `escalate`, `consequence`, `callback`, `reset` (no `reflection`).
- Every beat needs a `baseAsset` or at least one asset layer; a dark-canvas beat with only text/counter layers is rejected — reuse a scene background with `treatment` instead.
- Stacked text bands in vertical slots can collide in Y (`center` 640-1240 vs `right` 860-1240 on 1080x1920). Spread three or more simultaneous cards across `top-left`/`center`/`bottom`, or give them explicit boxes.
- Scene background cues may use only the tested transitions `wash`, `paper`, `ink`, `flash`, or `push`; do not invent transition names in authored plans.
- Treat `dialogue` and `counter` layers as reserved composition zones. Do not leave generic headline/caption text or a portrait box underneath them unless every box is explicitly separated by at least the validator gap; the preflight rejects predictable overlaps.
- Use `context`/`evidence`/`document` roles for `bg-*` assets and `person` only for square `portrait-*` assets. The plan preflight catches role drift before image generation.

## Vertical Images

- Declare `"size": "864x1536"` at the top level of `image_prompts.json`; generate fresh vertical backgrounds. Never crop landscape backgrounds into vertical use.
- `generate_images.py` swaps the landscape composition phrase in built-in style prefixes for a vertical one when height exceeds width. With a custom `stylePrefix`, the vertical phrase is prepended automatically; with `fullPrompt`, the author owns vertical framing.
- Write vertical prompts with the subject anchored in the middle vertical band and nothing important at the extreme top or bottom.
- Character portraits stay square 1024x1024 pure-white half-body images with an explicit Chinese-subject declaration; dialogue layers must bind portrait assets, same as landscape.
- Archive approved vertical assets back to the pool after QA per `../../../workflows/reuse-visual-assets.md`.

## Gates

Same staged gates as landscape, with the cheap contract checks made explicit: `preflight --stage content` → TTS → `build` → `evaluate` → `ready --stage plan` → `preflight --stage plan` → `images` (optionally `--limit 1` first to verify size and style) → `typecheck` → `intent-frames` review against every scene's `directorialIntent` → `ready --stage render` → `preflight --stage render` → `render` → ffprobe (1080x1920, 30fps, H.264 + AAC) → blackdetect → scene/beat contact-sheet review → `publish`.

Intent-frame review on vertical projects must additionally confirm: frame-0 cover type is readable at phone scale, the subtitle bar never overlaps text lanes, and image-top/text-bottom compositions actually hold.

The render preflight is mandatory. It checks that every compiled background and portrait is present in the project-local asset tree, that vertical dimensions are correct, and that `qa/intent-frame-review.json` says `pass`. This catches the two most expensive failures observed in production: late image 404s during a long Remotion render and text/layout defects that only appear in actual pixels.

## Improve Deliberately

Classify each finding exactly as in `produce-case-video` (case data, knowledge base, workflow, deterministic invariant, or skill routing). Vertical engine behavior lives in `engine/remotion/src/canvas.ts` plus the `IS_VERTICAL` branches in `VisualBeatTrack.tsx`, `SubtitleBar.tsx`, `CoverLayer.tsx`, `TransitionWipe.tsx`, `AnnotateLayer.tsx`, and `BrandBug.tsx`; keep `docs/knowledge-base/vertical-mobile-video.md` in sync with any change to those values.
