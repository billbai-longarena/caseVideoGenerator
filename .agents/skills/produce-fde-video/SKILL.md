---
name: produce-fde-video
description: Produce, revise, render, and quality-check Chinese FDE (Field Deployment Engineering) case stories and videos about AI system deployment as organizational change. Use for FDE case-story generation, narration, TTS, storyboards, assets, Remotion rendering, delivery QA, or production-system improvements specific to the FDE column.
---

# Produce FDE Video

## Start

1. Read `../../../docs/README.md` for the knowledge map.
2. Read `references/fde-narration-guide.md` for FDE-specific narration and content rules.
3. Read the workflow matching the task in `../../../workflows/`.
4. Read `../produce-case-video/references/project-contract.md` before creating or validating project artifacts.
5. Read `../produce-case-video/references/commands.md` before TTS, rendering, muxing, or QA.
6. Treat `output/<project>/` as case data. The shared engine lives in `engine/`; change it only for reusable behavior.

## FDE Column Identity

This skill produces videos for the **FDE不复杂** column. FDE (Field Deployment Engineering) covers AI system deployment as organizational change management.

- Column name: `FDE不复杂`
- Fixed opener: `这里是FDE不复杂，用真实的AI系统部署案例，帮您看懂变革、做对变革。`
- Fixed closer: `这期的《FDE不复杂》就到这里。看懂变革，做对变革，让AI系统真正落地。我们下期再见。`
- Set `storyboard.subtitleLabel` to `FDE不复杂`.
- Set `storyboard.brand` to `FDE不复杂`.

## FDE vs. Sales Column: Key Differences

| Dimension | 销售不复杂 | FDE不复杂 |
|---|---|---|
| Subject | Sales and sales management | AI system deployment as organizational change |
| Framework | 杨三角 + management theories | Change management theories (Lewin, Kotter, ADKAR, Bridges, etc.) |
| Core tension | Misdiagnosis of people problems | Misunderstanding of change itself |
| AI system role | Not a focus | Central — AI as "second brain" + "muscle memory" |
| Enterprise types | Industry-generic | Three-type matrix: 国央企, 民营企业, 在华外企 |
| Lifecycle dimension | Not structured | Five-stage lifecycle: 初创, 成长, 成熟, 转型/再创, 衰退/再生 |

## Route The Task

- **Generate or reconstruct an FDE case story**: Follow `references/fde-narration-guide.md` for FDE-specific structure, then the general `../../../workflows/generate-case-story.md`.
- **Create a complete FDE video**: Follow `../../../workflows/new-case-video.md`; apply FDE narration guide instead of the sales narration guide for story and narration.
- **Revise FDE narration or visuals**: Follow `../../../workflows/revise-video.md`; apply FDE column identity above.
- **Render or deliver**: Same pipeline as sales videos — plan readiness, project validation, typecheck, render readiness, render, ffprobe, and visual QA.
- **Review or audit FDE narration**: Verify against the FDE writing checklist in `references/fde-narration-guide.md`, not the sales-case narration checklist.

## Enforce Sources Of Truth

Identical to the sales skill (`../produce-case-video/SKILL.md`) — same file hierarchy, same schema-v2 plan as visual source of truth, same timeline baseline, same asset rules. The only differences are:

- Column identity (opener, closer, brand, subtitleLabel) uses FDE values above.
- Narration structure and content rules come from `references/fde-narration-guide.md`.
- Case model is optional for FDE cases (FDE cases are constructed, not reconstructed from sales call materials).

## Visual Style

FDE videos use the bright variant of the approved watercolor family (`fde-bright-watercolor`, finalized with ep01):

- Higher-key luminous sky/light cobalt blue, generous cream-paper negative space, sunny cadmium-yellow highlights, thin translucent watercolor/gouache washes, dry-brush edges, and light backgrounds without deep navy or heavy shadow areas.
- Backgrounds carry scene and atmosphere only: no clear human faces and no story characters in background art. People always appear as separate character-portrait assets (Chinese subject, pure-white background, half-body framing), never inside generated backgrounds.
- Keep the same production pipeline (Azure image generation, Remotion rendering) as sales videos.

## Director Loop & Production Gates

Same as the sales skill. The FDE narration guide adds FDE-specific beat requirements and theory integration rules, but the director loop, readiness gates, and QA process are shared.

## Improve Deliberately

Same classification as the sales skill. FDE-specific findings go to `references/fde-narration-guide.md`; shared pipeline findings go to the common knowledge base and workflows.
