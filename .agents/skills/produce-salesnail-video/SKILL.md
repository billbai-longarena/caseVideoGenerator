---
name: produce-salesnail-video
description: Generate SalesNail product case-story videos — from client brief to rendered MP4. Covers narration writing, TTS, storyboard planning, image generation, Remotion rendering, and QA for SalesNail AI sales/management training platform customer success stories.
---

# Produce SalesNail Case Video

## Overview

This skill produces case-story videos showcasing how SalesNail (AI 实战演练与培训平台) helps enterprise clients solve sales and management training problems. Each video tells a de-identified customer success story: discovering the problem, exploring failed alternatives, adopting SalesNail's sandbox simulation approach, and achieving measurable results.

## Start

1. Read `../../../docs/README.md` for the knowledge map.
2. Read `../../../input/salesnail/SALESNAIL-产品介绍.md` for product context.
3. Read `references/project-contract.md` from the produce-case-video skill for artifact rules.
4. Read `references/commands.md` from the produce-case-video skill for pipeline commands.
5. If a client course design exists under `../../../input/salesnail/<客户名>/`, read it for scenario context.

## SalesNail Product Knowledge

SalesNail's core value proposition for case videos:

- **AI 沙盘演练（牌桌）**: AI-driven sandbox simulation with NPC decision-makers, action cards, action points, and multi-team competition
- **AI 剧本创作工坊**: Auto-generate complete training scenarios from industry + client + procurement + decision-maker inputs
- **课程与培训管理**: Course creation, group management, instructor dashboards, approval workflows
- **神谕（方法论工具箱）**: Built-in FAB, SPIN, and other sales methodology AI tools
- **多模型 AI 工作台**: 12+ LLM models for enterprise AI infrastructure

Case videos should naturally weave these capabilities into the story arc without reading like a feature list.

## Client De-identification Rules

SalesNail case videos feature real client scenarios but must be fully de-identified:

1. **Company name**: Replace with a plausible fictional name in the same industry (e.g., 深圳华特容器 → 鑫达包装).
2. **All person names**: Use fictional Chinese names. Keep role titles accurate to the story.
3. **Remove identifying details**: Strip specific addresses, stock codes, parent company names, exact founding dates, and other traceable information.
4. **Preserve industry context**: Keep the industry, production scale, and business challenges realistic — these are essential to the story's credibility.
5. **At least 5 named characters**: Follow the project's 第一原则 — specific people + specific events. Include at minimum: the client-side champion, the problem exemplar, the SalesNail consultant, and 2+ training participants who demonstrate transformation.

## Narration Structure for SalesNail Cases

Every SalesNail case video follows this story arc:

### Act 1: The Pain (探索问题 + 发现问题)
- Open with a concrete incident that exposes the management or sales training gap
- Show measurable damage (退货率, 丢单率, 交付延迟, etc.)
- Name the person who feels the pain most acutely (usually HR/training lead or business unit head)

### Act 2: Failed Alternatives (克服困难)
- Show 2-3 traditional training approaches the client tried and why they failed
- Common patterns: external lecturers (理论脱节), MBA programs (成本高、脱产), internal mentoring (经验难复制)
- The pivot: how the champion discovered SalesNail

### Act 3: The Solution Design (面临选项)
- Introduce the SalesNail consultant by name
- Show the customization process: industry-specific scripts, role-based NPC design, multi-round simulation architecture
- Highlight the "管理三板斧" or similar framework adapted to the client's context

### Act 4: The Simulation Experience (实战过程)
- Walk through 2-3 simulation rounds with escalating difficulty
- Each round features a named participant making a specific mistake → learning → adjustment
- Show SalesNail platform mechanics naturally: cards, NPC responses, scoring, decision path visualization
- Include at least one direct quote from a participant during review

### Act 5: Measurable Results (解决问题)
- Hard metrics: before/after comparison (准时率, 响应时间, 续约率, etc.)
- Soft outcomes: voluntary re-enrollment, behavioral change quotes
- End with a one-line thesis connecting SalesNail to the transformation

## Visual Style

- Default to `sales-watercolor-blue-yellow`: bright cobalt/sky blue, cadmium yellow highlights, high contrast, cream paper, translucent watercolor/gouache washes
- Character portraits: Chinese people, white background, half-body, watercolor style
- Use `counter`, `bar-compare`, and `network` layers for key data and relationships
- Use `dialogue` layers for participant quotes — bind portrait assets

## Co-brand (SalesNail × WorkBuddy)

All `salesnail_sn<NNN>_video` 小红书 episodes are SalesNail × WorkBuddy joint-promotion videos and must carry the persistent top-right dual-logo co-brand bug. Follow `../../../docs/knowledge-base/salesnail-workbuddy-collab.md`: copy the canonical logos (`input/salesnail/SalesNail.svg`, `input/salesnail/workbuddy-logo-WhgOvEF7.png`) into the project `brand/` directory, declare top-level `coBrand` in the schema-v2 plan, and use the `salesnail-workbuddy-watercolor` visual family (SalesNail blue #3671DB/#75A7FF + WorkBuddy jade #00C090, taken from the two logos) for all generated images instead of the default sales blue/yellow watercolor. Omit `coBrand` for non-joint SalesNail cases (e.g. `salesnail_xinda_case_video`).

## Pipeline

The full pipeline reuses the shared case-video engine:

```bash
# 1. Write narration → output/<project>/narration.txt + title.txt
# 2. Generate TTS
scripts/case-video tts output/<project> --gender female --single-voice --force

# 3. Create storyboard_plan.json and image_prompts.json
scripts/case-video build output/<project>

# 4. Generate images
scripts/case-video images output/<project> --force

# 5. Rebuild and validate
scripts/case-video build output/<project>
scripts/case-video check output/<project>

# 6. Render
scripts/case-video typecheck output/<project>
scripts/case-video render output/<project>

# 7. QA and publish
scripts/case-video qa output/<project>
scripts/case-video publish output/<project>
```

## Project Naming

SalesNail case video projects use the pattern: `salesnail_<client_slug>_case_video`

Example: `salesnail_xinda_case_video` for the 鑫达包装 case.

## TTS Profile

Use the standard female narrator: `zh-CN-Xiaochen:DragonHDLatestNeural`, rate `+7%`, pitch `+1%`, paragraph gap `0.45s`. No column-specific opener/closer unless the user requests one — SalesNail cases are product cases, not part of the 销售不复杂 column.

## Duration

Default 4–7 minutes unless the user specifies otherwise. Control through narration length, not TTS rate adjustments.

## Quality Gates

1. **Narration**: At least 5 named characters, concrete incidents at every turning point, no abstract collective descriptions, no `不是……而是……` pattern.
2. **TTS**: Timeline units match audio, key segments pass listening test.
3. **Storyboard**: Every scene has `directorialIntent`, semantic visual gaps ≤ 12s, dialogue layers bind portrait assets.
4. **Images**: All backgrounds are AI-generated watercolor, character portraits are Chinese people with white background, no text/numbers/logos in backgrounds.
5. **Render**: 1920×1080, 30fps, H.264, video and audio duration match narration timeline.
6. **Delivery**: Master at `video/case_video.mp4`, compressed copy at `video/case_video_compressed_50m.mp4`.
