# Case Video Production Agent Guide

**第一原则：具体人物 + 具体事件。** 每个案例旁白必须有有名字的人物和具体的场景事件。关键转折必须绑定人物在哪里、做了什么、说了什么话。不能用"团队觉得""大家认为"等抽象集体表述替代具体人物反应。人物数量按剧情需要判断：3 分钟以下的视频可以只用 2 个具名人物，不为凑数硬加第三人；超过 3 分钟的视频默认至少 3 个具名人物。违反具体人物、具体事件或抽象集体表述禁令即为缺陷。

This repository is the dedicated workspace for generating case-story videos with Azure Speech TTS, Remotion, Azure image generation, and ffmpeg QA. Do video work here instead of in `/Users/bill.bai/Desktop/CeibsSalesTouch`.

## Primary Workflow

Before changing or generating video assets, read:

```text
docs/README.md
docs/knowledge-base/production-principles.md
workflows/new-case-video.md or workflows/revise-video.md
```

Use `.agents/skills/produce-case-video/SKILL.md` for sales-column (`销售不复杂`) production, revision, rendering, and QA tasks. Use `.agents/skills/produce-fde-video/SKILL.md` for FDE-column (`FDE不复杂`) production — it shares the same rendering pipeline but has its own narration guide, column identity, and content rules. Use `.agents/skills/produce-xiaohongshu-video/SKILL.md` for Xiaohongshu-first 2-3 minute vertical case videos (小红书竖屏短版) — primarily the 女性领导力 100 series; it inherits the vertical canvas contract and adds Xiaohongshu narration structure, pacing, cover design, and series matrix validation. Read the Budweiser workflow only for that historical case implementation or details not yet promoted into the project knowledge base.

For new narration or video generation, do not inspect or imitate old generated narration, timelines, storyboards, rendered videos, QA frames, or other completed `output/<project>/` artifacts as examples. Many historical outputs are known to be wrong. Read the production Skill and current source materials, then generate from the current workflow; only read an existing project's artifacts when the user explicitly asks to revise or audit that project.

The replicated pipeline is:

```text
case source/materials
-> title.txt + rewritten narration
-> numeric-normalized TTS script
-> Azure Speech TTS narration wav + narration.timeline.json
-> schema-v2 unit-anchored storyboard_plan.json
-> deterministic rich_storyboard.json render IR
-> fresh project visual generation plus post-QA visual-pool archive
-> Remotion motion-graphics render
-> ffprobe/ffmpeg visual QA
```

## Source Of Truth

- Keep the final human-authored article/video title in `title.txt`; create and review it together with `narration.txt`.
- Keep schema-v2 `storyboard_plan.json` as the authored visual source of truth for direction, scenes, layouts, Visual Beats, assets, camera, timing, layers, chrome, subtitles, keywords, and backgrounds.
- Treat `rich_storyboard.json` as deterministic render IR when a v2 plan exists. Do not hand-edit it or let the compiler invent creative choices; rich-only legacy projects remain compatible until migrated.
- Keep `storyboard.cover.title` as the rendered copy of `title.txt`, not a separately authored later title.
- Keep `narration.timeline.json` as the only timing baseline.
- Keep `assets/visual-pool/taxonomy.json` as the shared visual-label source and `asset_pool_usage.json` as project-local provenance for deliberate checkout.
- Do not hard-code scene timing or scene data into Remotion components when JSON-driven data exists.
- Do not choose layouts, motions, transitions, beat counts, card surfaces, or asset quotas by scene/beat index in builders, adapters, or Remotion. The LLM director plan must state those choices explicitly.
- Use narration unit numbers (`atUnit`, `units`) instead of handwritten seconds.

## Duration Defaults

- If the user does not name a target duration, generate case videos between 4 and 7 minutes.
- If the user names a target duration or duration range, follow that specification.
- Control duration primarily through narration length and only use small `AZURE_TTS_RATE` adjustments after the script is close.
- Verify final audio/video duration with `narration.timeline.json`, `ffprobe`, and visual QA before delivery.

## Program Column

- For sales-case videos, use the recurring column name `销售不复杂` unless the user says otherwise.
- Add this fixed opener to the narration: `这里是销售不复杂，用销售和管理经典案例帮您揭开销售的秘密。`
- Add this fixed closer to the narration: `这期的《销售不复杂》就到这里。帮你揭开销售的魔法秘密，让销售不再复杂。我们下期再见。`
- Set the subtitle-bar label (`storyboard.subtitleLabel`) to `销售不复杂` so the column name stays visible throughout the video.
- The subtitle-bar label must remain on one line; widen or scale the label area rather than wrapping `销售不复杂`.
- Prefer setting `storyboard.brand` to `销售不复杂` for sales-case videos, keeping per-scene `kicker` for the local chapter label.

## SalesNail × WorkBuddy 联名视频

- SalesNail 小红书系列（`salesnail_sn<NNN>_video`）是 SalesNail × WorkBuddy 联合推广；视频右上角常驻 SalesNail × WorkBuddy 双 Logo 标识，从封面帧到结尾一直显示。
- 联名系列使用专属明亮水彩家族 `salesnail-workbuddy-watercolor`：SalesNail 蓝（#3671DB/#75A7FF）主调 + WorkBuddy 青绿（#00C090）高光，取色自两个 Logo；chrome 经 `visualTheme` 的 `salesnail-workbuddy` 分支自动切换。
- 完整联名规范见 `docs/knowledge-base/salesnail-workbuddy-collab.md`；Logo 权威拷贝在 `input/salesnail/SalesNail.svg` 和 `input/salesnail/workbuddy-logo-WhgOvEF7.png`，项目内放 `brand/` 目录并在 schema-v2 plan 顶层声明 `coBrand`。

## Narration Style

- For Chinese case-video narration and subtitles, do not use the rhetorical contrast pattern `不是……而是……` or close variants such as `不是...而是...`.
- Rewrite those contrasts as direct assertions, causal statements, or two short sentences. Example: `软件上线改变了责任边界。`
- In human-readable `narration.txt`, screen subtitles, and normalizer-generated TTS text, keep business acronyms unspaced, such as `CEO`, `CIO`, and `CRM`; do not add spaces between acronym letters or between the acronym and adjacent Chinese text.
- Before finalizing `title.txt` and narration, run an explicit large-model review for title appeal and factual support, hook/title consistency, natural spoken Chinese, prohibited contrast patterns, acronym spacing, and numeric readout risks.
- When a case shares a category with a prior video, vary the narrative lens. Avoid repeating the same "sales discovers hidden need, upgrades the solution, wins a larger deal" arc if the source material supports a customer-transformation, internal-resistance, or organization-politics angle.

## TTS Rules

- The one-line final title goes in `title.txt`; human-readable narration goes in `narration.txt`.
- Spoken text must go through `tts_text_normalizer.py` before Azure Speech TTS.
- Screen subtitles may keep Arabic numerals for readability; TTS text should use normalized Chinese readings.
- Azure Speech TTS is the default engine for all future videos. CosyVoice is only a historical fallback unless the user explicitly asks for it.
- Current default Azure voice is female `zh-CN-Xiaochen:DragonHDLatestNeural`.
- Male `zh-CN-Yunfan:DragonHDLatestNeural` is a legacy/A-B option only when the user explicitly requests it.
- Generate narration as a single female voice by default; blank lines control paragraph pauses and synthesis chunks, not voice alternation.
- Default delivery profile is `dragon-broadcast`, selected from `B_broadcast.mp3`: synthesize whole paragraphs; female Xiaochen rate `+7%`, pitch `+1%`; paragraph gap `0.45s`.
- Use the same profile for the fixed opener, body, and closer. Never splice a slower opener/closer generated with legacy settings into the broadcast-profile body.
- Use `--gender female --single-voice --force` for current full TTS generation unless the user explicitly requests voice alternation.
- Use `AZURE_SPEECH_KEY`/`AZURE_SPEECH_REGION` or `AZURE_TTS_KEY`/`AZURE_TTS_REGION` when available. This workspace also accepts the verified legacy `.env` pair `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`/`AZURE_DOCUMENT_INTELLIGENCE_KEY`; do not print secrets.
- Keep acronyms such as `IT`, `ERP`, `CRM`, `SKU`, and `CIO` contiguous in both screen subtitles and TTS text. Do not use spaced-letter workarounds such as `I T` or `C E O`.
- For shopping-festival labels such as `618 大促`, screen subtitles may keep digits; TTS text should use digit-by-digit reading such as `六一八大促`.
- For short enumerations such as `年轻医生培养、学术水平和教学能力`, keep the screen/timeline unit stable but split TTS internally and insert a short inner pause. Do not renumber storyboard units just to fix prosody.
- Treat a single global `AZURE_TTS_RATE=+4%` as a legacy fallback. Preserve the approved female broadcast rate and pitch values unless a new listening test explicitly replaces the profile.
- Generate full narration with the repository command:

```bash
scripts/case-video tts output/medical_device_case_video --gender female --single-voice --force
```

The Azure generator writes `audio/narration_azure.wav`, `narration.tts.txt`, `narration.tts.plan.txt`, and `narration.timeline.json`.

## Image Generation

- Azure OpenAI credentials are read from this repository's `.env` first, then from the case project's `.env` if present.
- Do not print secrets or commit `.env`.
- Use abstract visual prompts. Do not send restricted PDF source text, long excerpts, or sample-video voice data to external providers.
- Sales videos use the approved blue/yellow watercolor family: bright cobalt/sky blue, cadmium yellow highlights, high contrast, cream paper, translucent watercolor/gouache washes, dry-brush edges, clear foreground subject, and semi-abstract low-detail background.
- FDE (AI-adoption) series videos use the bright variant of that watercolor family (`fde-bright-watercolor`): higher-key luminous sky/light cobalt blue, generous cream-paper negative space, sunny cadmium-yellow highlights, thin translucent washes, and light backgrounds without deep navy or heavy shadow areas.
- Custom-column videos (e.g. the E.Q.STAR 蒙淇星 family-growth column) may define a client brand family such as `montessori-bright-watercolor`: high-key cream paper, warm cadmium-yellow highlights, fresh grass-green accents, near-black foreground elements, generous negative space, no deep navy or heavy shadows. Carry the custom image style via the top-level `stylePrefix` in `image_prompts.json` and route Remotion chrome colors (`brandSurface`, `emphasis`, `networkEmphasis`) through `visualTheme` in `engine/remotion/src/theme.ts`, keeping legacy defaults unchanged.
- The baijiu column (`杯中故事`) uses `baijiu-bright-watercolor`: high-key cream-paper bright watercolor, warm amber/sorghum-gold highlights, light cobalt sky accents, generous negative space, no deep navy or heavy shadows; chrome routes through the `baijiu` branch of `visualTheme` (deep sorghum-amber `brandSurface`, amber `emphasis`/`networkEmphasis`).
- PPG PMC brand stories use `ppg-bright-watercolor`: high-key cream-paper bright industrial watercolor, clear sky/light steel-blue tones with soft zinc-grey and pale cadmium-yellow highlights, generous negative space, no deep navy, heavy shadows, or red tones; chrome routes through the `ppg` branch of `visualTheme` (deep steel-blue `brandSurface`, steel-blue `emphasis`/`networkEmphasis`). Brand stories about real historical figures may omit character portraits entirely (the Chinese-portrait contract applies to generated portraits); carry person presence with name cards, counters, and quote cards instead.
- The 女性领导力 100 (women's leadership, Xiaohongshu vertical) series uses `women-leadership-five-color-watercolor`, established by WL-002: high-key cream paper with leaf green `#59A55D`, warm yellow `#EFDB56`, mist blue `#7D9DC6`, warm orange `#ECA23F`, and terracotta red `#CA4D2A`; near-black ink foreground accents, generous negative space, and no deep navy or heavy shadows. Chrome routes through the five-color `women-leadership` theme branch. The earlier red-watercolor family is retired for all new and revised production. Full spec lives in `input/women_leadership_100/series_blueprint.md` §5.1.
- Character portraits in every series (sales, sales-management, FDE) must depict Chinese people; generation prompts must explicitly declare a Chinese subject along with the pure-white background and half-body framing, and render readiness blocks portrait prompts missing any of the three.
- Sales-management videos use the local warm manager-silhouette family by default: near-black foreground silhouettes, deep navy layers, cobalt blue, burnt orange/gray-peach backlight, cream-to-amber glow, cut-paper/screen-print feel, clean negative space, and no detailed faces. Do not convert manager videos into the sales watercolor style unless the user explicitly asks.
- Keep generated background prompts free of logos, readable text, numerals, letters, watermarks, UI screenshots, and source-document screenshots. Numbers, percentages, money, and acronyms belong in Remotion text layers, not in generated background art.
- Background images carry scene and atmosphere only: no clear human faces and no story characters in background art. People always appear as separate character-portrait assets (white background, half-body); never embed main characters or recognizable faces in generated backgrounds.
- Final backgrounds must be AI-generated or curated narrative illustrations. Do not use PIL/Canvas/SVG/programmatic diagrams, icon sets, flowcharts, dashboards, or placeholders as final video backgrounds.
- If image generation fails, fix the Azure image deployment/configuration or stop for review; do not fall back to programmatic images.
- For new video/background work, generate fresh project-local backgrounds first. Do not search or checkout the shared pool as the first step; use pool assets only when the user explicitly requests reuse, a revision needs visual continuity, or a scene intentionally calls back to a prior asset.
- When pool assets are deliberately reused, checkout selected assets into `output/<project>/images/pool/`; never reference the shared canonical path directly from a storyboard.
- Main flow must align storyboard refs with project-local files. Generated images are declared by `image_prompts.json`; deliberately checked-out pool images are declared by `asset_pool_usage.json`.
- Cross-project pool reuse is allowed when deliberate, but it is not the default way to fill new scenes. Repeating the same image within one video requires an intentional callback, comparison, evidence reveal, or explicit fallback marked with `reuse`/`allowBackgroundReuse`; it must not hide a visual gap.
- After newly generated images pass QA, rebuild and audit the pool so they become reusable.

## Remotion

The shared Remotion engine lives in:

```text
engine/remotion/
```

Common commands:

```bash
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
```

`scripts/case-video preview` and `scripts/case-video render` create a job-local Remotion workspace and call `engine/scripts/sync_assets.sh` there, copying storyboard/timeline JSON, images, audio, SFX, and optional BGM without touching another render's data. `VIDEO_PROJECT_DIR` is set automatically by the root command. Do not run `npm run sync`, `npm run preview`, `npm run render`, or `npx remotion` concurrently from the shared `engine/remotion/` directory; use the root command for all concurrent work.

## Vertical 9:16 Mobile Video

- Only produce vertical (1080x1920) video when the user explicitly asks for mobile/竖屏/9:16 output; landscape 1920x1080 stays the default.
- Use `.agents/skills/produce-vertical-video/SKILL.md` and `workflows/new-vertical-video.md`; the canvas contract and mobile best-practice values live in `docs/knowledge-base/vertical-mobile-video.md`.
- Declare `"canvas": {"width": 1080, "height": 1920}` at the top level of the schema-v2 `storyboard_plan.json`; the compiler passes it into `rich_storyboard.json` and Remotion renders that size automatically. Only 1920x1080 and 1080x1920 are supported.
- Vertical projects use `editorial` scenes only; the shared template layouts are 16:9-only and the validator rejects them on a vertical canvas.
- Vertical backgrounds: declare `"size": "864x1536"` in `image_prompts.json` (per-record `size` overrides for mixed assets; portraits stay 1024x1024). The image generator swaps style-prefix composition phrasing for vertical framing automatically. Never crop landscape backgrounds into vertical use.
- Engine vertical behavior is centralized in `engine/remotion/src/canvas.ts` plus `IS_VERTICAL` branches in `VisualBeatTrack.tsx`, `SubtitleBar.tsx`, `CoverLayer.tsx`, `TransitionWipe.tsx`, `AnnotateLayer.tsx`, and `BrandBug.tsx`; keep the knowledge-base doc in sync when those values change.
- Pull vertical content toward the center: platform overlay UI (视频号/小红书 top tabs, bottom avatar/description/action rail) covers the edges. The safe area keeps essential content between y 320 and y 1240, the brand chip sits at `top: 310`, and the subtitle bar floats at `bottom: 400`. The top-right ChapterBadge is never rendered on vertical.
- On-screen labels must be audience-facing: scene `chapter`/`kicker` render as visible text (kicker chip, cover, landscape badge, `chapter-circle` transitions). Never put internal director terms such as `钩子`/`悬念`/`反转` in them; those belong in `dramaticFunction`/`directorialIntent`.

## QA

After rendering, run ffprobe and extract a contact sheet or key frames. Check:

- video stream and audio stream exist
- 1920x1080, 30fps unless the storyboard intentionally changes it
- no black frames or blank canvas
- subtitles, headlines, keywords, and info cards do not overlap
- narration duration and video duration are close
- years, money, percentages, and ranges are spoken correctly

## Delivery

- Keep stable internal render names under each project: `video/case_video.mp4` for the master and `video/case_video_compressed_50m.mp4` for the upload copy. Both directories are generated artifacts and stay Git-ignored.
- After the master passes QA, prepare the upload copy and centralized release artifact with:

```bash
scripts/case-video publish output/<project>
```

- The command creates or validates the roughly 50 MB compressed copy, then stages `publish/<topic>/S001_<title>.mp4`. Three-digit numbering keeps a 100-video topic sorted correctly from S001 through S100. Each topic folder contains only uploadable MP4 files so it can be opened directly in YouTube or another publishing site's file picker. The sequence is inferred from names such as `fde_ep01` and `sales_management_case20`; add project-local `publication.json` for custom series, sequence, output-folder, width, or opt-out metadata.
- For batch website upload, run `scripts/case-video publish-batch output --pattern 'fde_ep*'`. Use the generated `publish/manifest.csv`, `publish/manifest.json`, or `publish/upload-list.txt` as the upload queue.
- `publish/` is a disposable, Git-ignored release view. Do not treat it as an authored source or commit its video files.

## Locality

All future generated videos should be produced inside this repository. The old CeibsSalesTouch project is only a historical reference unless the user explicitly asks to inspect it.

## Termite Protocol / Blackboard Collaboration

This repository adopts the local, offline mode of [TERMITE_PROTOCOL.md](TERMITE_PROTOCOL.md) v5.1. The protocol governs agent collaboration and handoff; it does not replace the video-production workflow above.

- At the start of each substantive task, or when the user says `白蚁协议`, run `scripts/field-arrive.sh "<task summary>"`, then read `.birth`, `BLACKBOARD.md`, and any matching `ALARM.md`/`WIP.md` before making changes.
- Treat `BLACKBOARD.md` as the human-readable shared state, `signals/active/*.yaml` as actionable work signals, and `DECISIONS.md` as the durable record of choices. Trust the repository and verification output over stale blackboard text; correct drift when found.
- Select a role before acting: scout for investigation/review, worker for planned implementation, soldier for an alarm or failing build/test, and nurse for documentation or test maintenance. Work only within that role's permissions.
- Human instructions take priority. For material work, leave a durable trace: update the relevant signal/blackboard or decision record, and use a clear commit message. If work is incomplete, write `WIP.md`; if changes exceed 50 lines, make a `[WIP]` commit before continuing when appropriate.
- Stop and read `ALARM.md` before touching an affected area. Do not silently delete protocol, blackboard, decision, or other Markdown control files.
- Runtime files (`.birth*`, `.field-breath`, `.pheromone`, optional `.termite.db*`) stay local and are ignored. This project does not enable external telemetry or audit export unless the user explicitly asks.
