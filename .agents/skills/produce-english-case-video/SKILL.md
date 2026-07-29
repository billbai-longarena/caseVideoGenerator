---
name: produce-english-case-video
description: Produce, revise, render, and quality-check native-English case-story videos in this repository. Use for English-language business case narration, English TTS direction, schema-v2 storyboards, blue-and-black silhouette visuals, Remotion rendering, and delivery QA.
---

# Produce English Case Video

## Start

1. Read `../../../docs/README.md` for the repository knowledge map.
2. Read the workflow matching the task in `../../../workflows/`, usually `new-case-video.md` for a new video or `revise-video.md` for a revision.
3. Read `../produce-case-video/references/project-contract.md` and `../produce-case-video/references/commands.md` for the current artifact contract and repository commands. Apply the shared pipeline contract, not the Chinese creative defaults.
4. Treat `output/<project>/` as case data. The shared engine lives in `engine/`; change it only for reusable behavior that benefits more than one project.

## Purpose

This skill produces native-English case videos, not translated versions of Chinese videos. The final title, narration, subtitles, on-screen text, image prompts, review notes, and delivery checks must be written for an English-speaking business audience from the start.

Use this skill when the user asks for an English case video, an English version of a sales or management case, an English TTS/render pass, or a new English production style that should stay related to the case-video series while remaining visually distinct.

## Native English Direction

- Build the case from source facts, then write it as original English business narration. Do not translate Chinese sentence rhythm, idioms, openings, closers, or rhetorical habits.
- If source material is not in English, extract verified facts first, then recast the explanation in natural English. Preserve real people, companies, places, dates, and outcomes when they are source facts; use English-speaking cultural context only for framing, examples, composites, and unspecified settings.
- Prefer English business roles and settings such as account executives, regional sales directors, procurement committees, customer success teams, boardrooms, field offices, channel partners, SaaS buyers, hospital administrators, university deans, dealership groups, or enterprise CIO teams when the case allows composite or generalized framing.
- Avoid Chinese cultural markers, Chinese signage, Chinese architecture, Chinese classroom framing, Chinese corporate slogans, and translated Chinese honorifics unless the verified case facts require them.
- Keep acronyms contiguous in screen text and narration: CEO, CIO, CRM, ERP, SKU, SaaS, ARR, ACV, ROI.
- Write for spoken clarity: active voice, concrete nouns, short paragraphs, clean causal links, and idiomatic English business phrasing.
- Avoid formulaic contrast patterns such as "not X but Y" when they become a repeated structure. Prefer direct claims, cause-and-effect, and visible decisions.

## English Series Package

- Use the recurring English column name `Sales Made Clear` unless the user names another English brand.
- Use this opener by default: `This is Sales Made Clear, where classic sales and management cases reveal how selling really works.`
- Use this closer by default: `That is all for this episode of Sales Made Clear. We will see you next time.`
- Set `storyboard.subtitleLabel` to `Sales Made Clear` and keep it on one line.
- Set `storyboard.brand` to `Sales Made Clear` unless the user provides another English brand.
- Keep `storyboard.cover.title` synchronized with `title.txt`.

## Visual Identity

The approved English-case family is a cool blue-and-black silhouette style:

- Near-black foreground silhouettes with deep navy and midnight-blue layers.
- Cobalt, electric blue, steel blue, and ice-blue highlights.
- Cool rim light, glassy blue-gray depth, editorial cut-paper or screen-print texture, crisp negative space, and no detailed faces.
- Clear foreground business action: negotiation, decision rooms, corridor conversations, sales calls, field visits, executive reviews, or customer operations.
- Backgrounds should feel English-speaking or globally Western business by default: modern offices, conference rooms, city towers, airport lounges, trade shows, hospitals, universities, dealerships, warehouses, or SaaS command centers.

Do not use the warm Chinese management palette as the default for English videos: no burnt orange, amber glow, gray-peach backlight, cadmium yellow, or cream-orange dominance unless the user explicitly asks for a special exception. Keep series continuity through silhouettes, disciplined negative space, high contrast, and the shared motion-graphics grammar, not through the warm palette.

## Image Prompt Rules

- Write image prompts in English.
- Generate fresh project-local images for new videos before considering shared-pool reuse.
- Ask for illustration-like narrative backgrounds, not UI screenshots, source-document screenshots, diagrams, flowcharts, stock photos, icon sets, or placeholder graphics.
- Keep prompts free of readable text, letters, numerals, logos, watermarks, and brand marks. Put numbers, percentages, money, and acronyms in Remotion text layers instead.
- Keep characters consistent with the English case context. Do not introduce Chinese visual cues as a shortcut for "business" or "management".
- If image generation fails, fix the provider configuration or stop for review. Do not replace final backgrounds with PIL, Canvas, SVG, or programmatic diagrams.

## Production Route

- Keep `title.txt` as the final one-line English title and create it with `narration.txt`.
- Keep human-readable English narration in `narration.txt`.
- Use an English Azure Speech voice and profile for TTS. Do not synthesize English narration with Chinese voices. If the current repository command lacks an English voice/profile, add or configure one before generating final audio.
- Generate spoken text through the repository TTS normalizer or an English-safe equivalent. Verify dates, money, percentages, ranges, acronyms, and proper nouns by listening or inspecting the TTS plan.
- Keep `narration.timeline.json` as the timing baseline.
- Author the schema-v2 `storyboard_plan.json` as the visual source of truth. Use narration unit anchors, not handwritten seconds.
- Treat `rich_storyboard.json` as deterministic render IR when a v2 plan exists. Rebuild it through the compiler; do not hand-edit it.
- Use the LLM director loop for visual planning: visual thesis, dramatic function, directorial intent, explicit asset casting, explicit composition, Visual Beats, and actual-pixel review.
- Run staged readiness, validation, typecheck, render, ffprobe, and visual QA before delivery.

## English Quality Gates

Before final render or delivery, explicitly check:

- `title.txt`, `narration.txt`, subtitles, cover copy, scene chrome, keywords, and image prompts contain English only.
- The video does not read like a Chinese script translated into English.
- The cultural setting, names, roles, metaphors, and business examples fit an English-speaking or global Western business audience unless source facts require otherwise.
- The visual palette is cool blue and black, not orange-yellow and black.
- Every generated background is visible behind Remotion layers; text panels, covers, subtitles, and controls do not hide the main image.
- Audio and video durations match closely, and the final file has both video and audio streams.

Use a CJK scan on authored project text before delivery:

```bash
rg -n "[\\p{Han}\\p{Hiragana}\\p{Katakana}\\p{Hangul}]" \
  output/<project>/title.txt \
  output/<project>/narration.txt \
  output/<project>/storyboard_plan.json \
  output/<project>/rich_storyboard.json \
  output/<project>/image_prompts.json
```

If the scan finds text that is not a source-required proper noun, revise the authored artifact before rendering.

## Improve Deliberately

Promote reusable findings only when they are stable across English case-video tasks:

- case-specific choice: keep it in `output/<project>/`
- English writing method: update the relevant knowledge-base document or workflow
- ordered production gate: update `workflows/`
- deterministic invariant: update schema, builder, validator, and tests
- task routing or cross-stage guardrail: update this skill

Do not weaken the Chinese video skill to support English work. Keep English creative defaults here and shared pipeline behavior in reusable repository code.
