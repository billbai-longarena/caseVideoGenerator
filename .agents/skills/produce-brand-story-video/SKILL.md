---
name: produce-brand-story-video
description: Produce, revise, render, and quality-check Chinese brand story videos. Use for brand narration writing, TTS, storyboards, asset generation, Remotion rendering, delivery QA, or production-system improvements. Brand stories differ from sales/management case videos — the narrative engine is discovery (value progressively revealed through real people, real technology, and real project results), not suspense (information gap between sales cognition and customer truth).
---

# Produce Brand Story Video

## Start

1. Read `../../../docs/README.md` for the knowledge map.
2. Read `../../../docs/knowledge-base/brand-story-narration.md` for the brand story narration guide (骨架、beat 合同、禁止写法、写作检查).
3. Read `../../../docs/knowledge-base/narration.md` for shared TTS/pacing/口播 rules (these apply to all video types).
4. Read the workflow matching the task in `../../../workflows/`.
5. Read `references/project-contract.md` before creating or validating project artifacts.
6. Treat `output/<project>/` as project data. The shared engine lives in `engine/`; change it only for reusable behavior.

## What Is Different From Case Videos

Brand story videos do NOT use:
- `case-story-model.md`'s three-layer model (客户真相/披露路径/销售认知)
- `case_model.json` or `case_inputs.json`
- Suspense engines or reveal-position planning
- The sales/management 双线骨架 or 九段骨架 as-is

Brand story videos DO use:
- `brand-story-narration.md`'s 短片骨架 (5-part, 2-3 min) or 标准骨架 (7-part, 4-7 min)
- The "发现" (discovery) narrative engine: value progressively revealed through evidence
- Real brand names, real people (or named archetypes), real projects throughout the story body
- The same shared TTS, pacing, 口播, and forbidden-pattern rules from `narration.md`

## Route The Task

- **Write brand story narration**: Follow `brand-story-narration.md` writing order. Choose 短片骨架 or 标准骨架 by target duration. Write `title.txt` and `narration.txt` in the same editorial step. Immediately create the project folder and persist `narration.txt` to disk.
- **Create a complete video**: Follow `../../../workflows/new-case-video.md` for the pipeline (TTS → timeline → storyboard → assets → render → QA), substituting the brand story narration guide for the case narration guide.
- **Change narration or timing**: Follow the audio path in `../../../workflows/revise-video.md`.
- **Change storyboard or visuals**: Follow the visual path in `../../../workflows/revise-video.md`.
- **Review or audit narration**: Verify `narration.txt` against every item in the writing checklist at the end of `brand-story-narration.md`, then cross-check shared rules from `narration.md` (禁用句式, TTS 归一化, 缩写, 数字读法). Do not treat review as a surface pattern-scan.
- **Render or deliver**: Run the same staged readiness gates as case videos.

## Enforce Sources Of Truth

- Keep the final title in `title.txt` (one line, no labels or markdown).
- Keep human-readable narration in `narration.txt`.
- Generate spoken text through the shared TTS normalizer.
- Keep `narration.timeline.json` as the only timing baseline.
- All other source-of-truth rules from the case video skill apply (storyboard_plan.json v2, rich_storyboard.json as render IR, asset provenance, unit-based timing, cover requirements).

## Brand-Specific Narration Rules

### People requirement by duration

| Duration | Named people | Action scenes |
| --- | --- | --- |
| 4-7 min | ≥3 | Key turns bound to concrete scenes |
| 2-3 min | ≥2 | ≥1 action scene + ≥1 quote or specific number |
| 1-2 min | ≥1 | ≥1 action scene |

### Forbidden patterns (in addition to shared rules)

- Slogan piling: "我们始终致力于..." / "公司秉持..."
- Feature listing: "具有优异的耐腐蚀性、耐候性、附着力..."
- Subjectless declarations: "我们相信" / "品牌坚持"
- Teaching paragraphs: any character or narrator stopping to explain brand philosophy
- Abstract collective statements: "团队觉得" / "大家认为"

### Duration budget

- 2 min target: ~580-640 Chinese characters (body, excluding opener/closer)
- 4-7 min target: ~1200-2100 Chinese characters
- Paragraph gaps produce natural pauses; count them in the budget

## Run The Director Loop

Same as the case video skill's director loop. The only difference: each brand story's visual family should be determined per-project from an authorized private brand guide, not assumed from the sales watercolor or FDE bright-watercolor families.

## Character Portraits — Required When Dialogue Layers Are Used

Brand stories frequently use `dialogue` layers to put words in specific people's mouths. Every dialogue layer **must** bind a character portrait before images are generated. Forgetting this produces dialogue bubbles with no speaker image, which the validator will not catch as a hard blocker (only a warning).

Checklist to run **at storyboard authoring time**, before calling `scripts/case-video images`:

1. List every named person who appears in a `dialogue` layer across the full plan.
2. For each person, assign a stable `portrait-<slug>` asset ID (e.g. `portrait-yang-fan`, `portrait-chen-mo`).
3. Add each portrait to `image_prompts.json` (or `portrait_prompts.json` for square 1024×1024 renders) with:
   - explicit `Chinese person` declaration in the prompt
   - pure white background, half-body framing
   - project visual family style
4. Set `"asset": "<portrait-id>"` on every dialogue layer for that person.
5. Run `scripts/case-video check output/<project>` — the validator now warns on any dialogue layer missing an `asset`.
6. Generate portraits via `scripts/case-video images output/<project>` (portraits are generated alongside backgrounds).

Do **not** proceed to `ready --stage plan` until all dialogue `asset` fields are filled.

## Preserve Creative Freedom

- Apply current defaults from knowledge-base without duplicating values here.
- Do not encode fixed shot counts, beat counts, asset quotas, or template rotations.
- Each brand story has its own visual character; do not force a single visual family across all brand clients.

## Improve Deliberately

Same classification system as the case video skill:
- case-specific → `output/<project>/`
- reusable brand-story method → `docs/knowledge-base/brand-story-narration.md`
- ordered step or quality gate → `workflows/`
- deterministic invariant → schema, builder, validator, tests
- task routing or brand-story guardrail → this Skill
