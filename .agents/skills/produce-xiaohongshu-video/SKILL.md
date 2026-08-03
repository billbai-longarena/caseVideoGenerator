---
name: produce-xiaohongshu-video
description: Plan, produce, revise, render, and quality-check 2-3 minute vertical 9:16 (1080x1920) case-story videos optimized for Xiaohongshu (小红书), including cross-model production-parameter handoffs. Use for 小红书视频, 女性领导力 series production, short-form vertical cases, 制作参数预案, or workflows where one model plans the title, narration direction, theory gold-sentence, and video parameters while another model executes them. Inherits the vertical canvas contract, TTS pipeline, and QA gates from produce-vertical-video.
---

# Produce Xiaohongshu Video

## Start

1. Read `../../../docs/knowledge-base/vertical-mobile-video.md` for the canvas contract and mobile best-practice values.
2. Read `../../../docs/knowledge-base/editorial-component-contract.md` for the mandatory boundary between model-authored direction and deterministic Remotion mechanics.
3. Read `../../../workflows/new-xiaohongshu-case-video.md` for the ordered stages and gates.
4. Read `../produce-case-video/references/project-contract.md` and `../produce-case-video/references/commands.md`; every contract there still applies unless this skill overrides it.
5. If producing from the 女性领导力 100 series, read `../../../input/women_leadership_100/series_blueprint.md` for the theory framework, matrix, and duration spec.
6. Read the specific season topic file (e.g., `../../../input/women_leadership_100/S01_选题_01-10.md`) for the episode's matrix code, characters, and synopsis.
7. When planning a new episode or executing another model's plan, read `references/production-parameters-contract.md` and the project-local `production_parameters.txt` if it exists.

## What Is Different From Standard Case Videos

Xiaohongshu case videos do NOT use:
- `case-story-model.md`'s three-layer model (客户真相/披露路径/销售认知)
- `case_model.json` or `case_inputs.json`
- Suspense engines or reveal-position planning
- The sales 九段骨架
- Fixed opener "这里是销售不复杂" or closer — this is a separate column
- 4-7 minute default duration — Xiaohongshu default is 2-3 minutes

Xiaohongshu case videos DO use:
- The 2-3 minute vertical structure from `new-xiaohongshu-case-video.md`
- Conflict-first opening (no intro, no column branding in first 3 seconds)
- 2 or more named people for the short version, chosen by story need; never add a third person only to satisfy a quota
- 1 core scene event (not 2+) for the short version
- Theory gold-sentence (理论金句) — one sentence, under 15 seconds
- Save/comment call-to-action at the end
- Series matrix validation (theory coverage, arc variety, industry diversity)

## Route The Task

- **Produce a new episode from the series**: Follow `../../../workflows/new-xiaohongshu-case-video.md` end to end, starting from Step 0 (matrix validation).
- **Plan only / wait for approval**: Create the project directory and `production_parameters.txt` from `references/production-parameters-contract.md`, set `APPROVAL_STATUS: WAITING_FOR_APPROVAL`, then stop. Do not create `title.txt`, narration, TTS, image prompts, storyboards, images, or video.
- **Execute another model's plan**: Read `production_parameters.txt` first. Continue only when `APPROVAL_STATUS: APPROVED`, every pending decision is resolved, and the approved package still satisfies source and hard production contracts. Preserve its locked title, gold sentence, people, event, visual family, and delivery parameters unless the user re-approves a change.
- **Write narration only**: Follow Steps 0-2 of the workflow; validate matrix code, write `title.txt` and `narration.txt`, persist immediately.
- **Batch-plan a season**: Read the season topic file, validate all 10 matrix codes against `series_blueprint.md`, output a coverage check. Do not generate narration or video artifacts.
- **Create a complete video from existing narration**: Start from Step 3 (TTS) of the workflow.
- **Revise narration or visuals**: Follow `../../../workflows/revise-video.md`, applying Xiaohongshu narration rules instead of standard case rules.
- **Review or audit narration**: Verify against the Xiaohongshu narration checklist below (not the sales case checklist).
- **Produce long version alongside**: Follow the "长版差异" section in Step 2 of the workflow, writing `narration_long.txt` as a separate file.

## Xiaohongshu Narration Structure (2-3 minutes, 500-750 words)

```
00:00-00:05  Hook: sharpest conflict moment (one sentence)
00:05-00:30  Character + dilemma quick setup
00:30-01:15  Core conflict scene: specific event (who, where, what was said)
01:15-01:50  Turning point: key behavior or dialogue
01:50-02:20  Result + behavior change
02:20-02:35  Theory gold-sentence (one-line insight)
02:35-02:45  Closing + save/comment CTA
```

## Narration Rules

### First 3 Seconds — Non-negotiable
- Open with the conflict scene itself. No self-introduction, no column branding, no topic preview, no background setup.
- Formula: "具体场景 + 反常结论". Example: "她被提拔的那天，团队里没有一个人鼓掌。"

### Character & Scene Requirements (Short Version)
| Element | Xiaohongshu 2-3 min | Long version 4-5 min |
|---------|---------------------|---------------------|
| Named characters | 2 or more, chosen by story need | Normally 3 or more |
| Core scene events | 1 (ultra-focused) | 2+ |
| Theory insertion | 1 gold sentence, ≤15 sec | 30 sec theory paragraph |
| Opening | No preamble, conflict-first | Brief context OK |
| Pacing | Info anchor every 20-30 sec | Info anchor every 30-45 sec |
| Closing | Save/comment CTA | Column closer + next episode |

### Theory Gold-Sentence Contract
- Exactly one theoretical insight, stated as a memorable sentence.
- Must emerge naturally from the story climax — not appended as a lecture.
- Names the theory or researcher only if it fits naturally (e.g., "Eagly 把这叫做角色一致性陷阱").
- Designed to be screenshot-worthy: concise, quotable, save-triggering.

### Cross-Model Production Parameters Handoff

- Store the planning package at `output/<project>/production_parameters.txt` as UTF-8 plain text.
- The planning model writes title candidates, selected hook direction, the story-required named people (2 are allowed under 3 minutes), the concrete event chain, turning behavior, result, theory gold sentence, CTA, narration budget, canvas, pacing, visual family/palette, image counts/sizes, TTS profile, and unresolved approval choices.
- Use only the lifecycle values `DRAFT`, `WAITING_FOR_APPROVAL`, `APPROVED`, or `SUPERSEDED` for `APPROVAL_STATUS`.
- Treat `WAITING_FOR_APPROVAL` as a hard stop. The execution model must not generate downstream authored or paid artifacts.
- Promote the file to `APPROVED` only after recording the user's resolved choices and removing all `PENDING` values.
- Validate planning structure with `python .agents/skills/produce-xiaohongshu-video/scripts/validate_production_parameters.py output/<project>/production_parameters.txt`. Before execution, rerun it with `--require-approved`; any nonzero exit is a hard stop.
- After approval, `title.txt`, `narration.txt`, and `storyboard_plan.json` remain their established authored sources of truth. They must faithfully instantiate the locked brief. Any material drift in title, people, event, theory sentence, visual family, canvas, duration, or voice returns the package to approval.
- Do not use the brief as a substitute for timeline, storyboard, prompt manifests, readiness reports, or QA evidence.

### Forbidden Patterns (in addition to CLAUDE.md shared rules)
- Abstract collective statements: "团队觉得" / "大家认为" / "公司决定"
- `不是……而是……` contrast pattern
- Teacher-lecture theory blocks: "根据XX理论，我们可以看到……"
- Column branding in first 5 seconds
- "今天我们来讲一个故事" / "接下来让我们看看" and similar preview phrasing
- Narration that reads like a textbook summary rather than a specific person's experience

### Word Count & Duration Targets
| Version | Words | Duration | TTS rate |
|---------|-------|----------|----------|
| Xiaohongshu | 500-750 | 2:00-3:00 | Default |
| Long | 1000-1300 | 4:00-5:00 | Default |

## Xiaohongshu Visual Contract (additions to vertical-mobile-video.md)

### Cover Frame (Frame 0)
- Hook title in large emotional text (up to 100px), readable at phone thumbnail size.
- Background: the most conflict-charged scene image.
- Do not turn the cover into a column-introduction slate. The hook title remains the focal point; the persistent top-left series BrandBug may appear from frame 0 when enabled by the plan.
- Must survive Xiaohongshu's square thumbnail crop (center 1:1 area must contain the full title).

### Editorial Component Responsibility Contract
- The model owns narrative purpose, Visual Beats, asset identity, audience-facing copy, semantic treatment, timing, and explicit composition reservations (`box`). It must not delegate missing creative choices to the compiler or rotate layouts by scene/beat index.
- Remotion owns repeatable mechanics: true pixel-square portrait frames inside the reserved region, centered placement, `contain` media fit, card material, palette routing, animation interpolation, chrome stacking, and the exact cover handoff.
- Story text in the 女性领导力 series uses light cream text on bounded dark `glass`/`solid` surfaces. Bare critical text directly over watercolor imagery is not delivery-ready.
- Every person asset has an explicit reservation `box`. Any concurrently visible semantic panel also has an explicit `box`, with at least `0.012` normalized separation; strict validation must reject collisions instead of silently moving layers.
- The cover exclusively owns its active frames. Underlying BrandBug, subtitle, chapter chrome, and story layers stay suppressed until the shared `coverEndFrame()` handoff; the opening beat must not duplicate the cover sentence.
- The first post-cover hook beat should visualize evidence through counters, comparisons, bars, or other semantic motion when the story supplies it. A sequence of plain text fades is insufficient merely because it is animated.

### Theory Gold-Sentence Frame
- Design one visually prominent frame during the theory insertion:
  - Large text (72px+), high contrast against background.
  - Clear enough to screenshot and share.
  - Functions as a "save trigger" — the visual equivalent of a bookmark-worthy quote.

### Beat Pacing
- Target 4-6 seconds per beat (faster than standard vertical's 4-8 seconds).
- 12-second semantic gap ceiling still applies but should rarely be reached.

### Closing Frame
- Save/comment CTA text visible on screen.
- Topic hashtags can appear as visual elements.

## Series Matrix Validation

When producing episodes from the 女性领导力 100 series:

1. Read the episode's matrix code from the season topic file.
2. Cross-check against `series_blueprint.md` Appendix A (theory usage quota) and Appendix B (industry coverage).
3. Verify the anti-repetition rule: no two episodes share the same A+C+E combination.
4. After completion, update the "已使用" counts in the blueprint.
5. Every 10 episodes, run a full matrix coverage audit.

## Column Identity

| Item | Status |
|------|--------|
| Column name | 暂用「女性领导力」(正式栏目名待定,如 「她的领导力」/「她力量」/「镜中人」) |
| TTS voice | zh-CN-Xiaochen:DragonHDLatestNeural (female) |
| Visual family | `women-leadership-five-color-watercolor`, established by WL-002: high-key cream paper with leaf green `#59A55D`, warm yellow `#EFDB56`, mist blue `#7D9DC6`, warm orange `#ECA23F`, terracotta red `#CA4D2A`, near-black ink foreground accents, and generous negative space. This is the only family for new or revised 女性领导力 production. Full spec: `input/women_leadership_100/series_blueprint.md` §5.1. |
| Subtitle label | = column name (`女性领导力`) |
| Fixed opener | None (conflict-first opening) |
| Fixed closer | Save/comment CTA (e.g. 「收藏这条,等你升职那天翻出来看」) |

## Narration Audit Checklist

Before advancing past Step 2:

- [ ] Word count 500-750 (Xiaohongshu version)
- [ ] First two sentences are conflict scene (no intro, no setup)
- [ ] At least 2 named people with clear causal roles; add more only when the story needs them, and attribute every key reaction concretely
- [ ] At least 1 specific scene event: who + where + what action/dialogue
- [ ] Turning point bound to a concrete behavior (not "她渐渐意识到")
- [ ] Theory gold-sentence: ≤2 sentences, naturally embedded, screenshot-worthy
- [ ] Closing has save/comment CTA
- [ ] No abstract collective statements
- [ ] No `不是……而是……` pattern
- [ ] No teacher-lecture theory blocks
- [ ] No column branding in first 5 seconds
- [ ] Pacing: info anchor every 20-30 seconds
- [ ] Matrix code matches approved topic
- [ ] Story arc matches designated E-type from the matrix

## Production Gates

Same staged gates as vertical video, with these additional checks:

| Gate | Xiaohongshu Addition |
|------|---------------------|
| Plan readiness | Cover title ≤20 chars, conflict-first, gold-sentence frame designed, explicit person/panel reservations with no collisions |
| TTS duration | 2:00-3:00 range enforced; out-of-range → back to narration |
| Intent frames | Frame 0 plus both sides of the cover handoff; first appearance of every portrait; gold-sentence frame; cover survives square crop |
| Final QA | No bare critical text, no portrait/panel collision, persistent brand visible as planned, publish checklist prepared |

## Improve Deliberately

Classify findings as in `produce-case-video`. Xiaohongshu-specific narration structure and pacing rules live in this skill and `workflows/new-xiaohongshu-case-video.md`; editorial ownership and deterministic component rules live in `docs/knowledge-base/editorial-component-contract.md`; vertical engine behavior lives in `engine/remotion/src/canvas.ts` and the `IS_VERTICAL` branches. Keep all three in sync when engine behavior changes.
