# Case Video Production Agent Guide

This repository is the dedicated workspace for generating case-story videos with Azure Speech TTS, Remotion, Azure image generation, and ffmpeg QA. Do video work here instead of in `/Users/bill.bai/Desktop/CeibsSalesTouch`.

## Primary Workflow

Before changing or generating video assets, read:

```text
docs/README.md
docs/knowledge-base/production-principles.md
workflows/new-case-video.md or workflows/revise-video.md
```

Use `.agents/skills/produce-case-video/SKILL.md` for production, revision, rendering, and QA tasks. Read the Budweiser workflow only for that historical case implementation or details not yet promoted into the project knowledge base.

The replicated pipeline is:

```text
case source/materials
-> rewritten narration
-> numeric-normalized TTS script
-> Azure Speech TTS narration wav + narration.timeline.json
-> unit-anchored rich_storyboard.json
-> generated AI narrative illustration/background assets
-> Remotion motion-graphics render
-> ffprobe/ffmpeg visual QA
```

## Source Of Truth

- Keep `rich_storyboard.json` or the equivalent storyboard JSON as the source of truth for scenes, layouts, subtitles, keyword timing, and background cues.
- Keep `narration.timeline.json` as the only timing baseline.
- Do not hard-code scene timing or scene data into Remotion components when JSON-driven data exists.
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

## Narration Style

- For Chinese case-video narration and subtitles, do not use the rhetorical contrast pattern `不是……而是……` or close variants such as `不是...而是...`.
- Rewrite those contrasts as direct assertions, causal statements, or two short sentences. Example: `软件上线改变了责任边界。`
- In human-readable `narration.txt`, screen subtitles, and normalizer-generated TTS text, keep business acronyms unspaced, such as `CEO`, `CIO`, and `CRM`; do not add spaces between acronym letters or between the acronym and adjacent Chinese text.
- Before finalizing narration, run an explicit large-model review for natural spoken Chinese, prohibited contrast patterns, acronym spacing, and numeric readout risks.
- When a case shares a category with a prior video, vary the narrative lens. Avoid repeating the same "sales discovers hidden need, upgrades the solution, wins a larger deal" arc if the source material supports a customer-transformation, internal-resistance, or organization-politics angle.

## TTS Rules

- Human-readable narration goes in `narration.txt`.
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

- Azure OpenAI credentials are read from this repository's `.env` first, then from `output/budweiser_apac_story_video/.env` if present.
- Do not print secrets or commit `.env`.
- Use abstract visual prompts. Do not send restricted PDF source text, long excerpts, or sample-video voice data to external providers.
- Sales videos use the approved blue/yellow watercolor family: bright cobalt/sky blue, cadmium yellow highlights, high contrast, cream paper, translucent watercolor/gouache washes, dry-brush edges, clear foreground subject, and semi-abstract low-detail background.
- Sales-management videos use the local warm manager-silhouette family by default: near-black foreground silhouettes, deep navy layers, cobalt blue, burnt orange/gray-peach backlight, cream-to-amber glow, cut-paper/screen-print feel, clean negative space, and no detailed faces. Do not convert manager videos into the sales watercolor style unless the user explicitly asks.
- Keep generated background prompts free of logos, readable text, numerals, letters, watermarks, UI screenshots, and source-document screenshots. Numbers, percentages, money, and acronyms belong in Remotion text layers, not in generated background art.
- Final backgrounds must be AI-generated or curated narrative illustrations. Do not use PIL/Canvas/SVG/programmatic diagrams, icon sets, flowcharts, dashboards, or placeholders as final video backgrounds.
- If image generation fails, fix the Azure image deployment/configuration or stop for review; do not fall back to programmatic images.
- Main flow must align storyboard scene count, `image_prompts.json` prompt files, primary background refs, and actual image files. Reusing an earlier image is only an explicit fallback marked with `reuse`/`allowBackgroundReuse`; it must not hide missing generated images.

## Remotion

The current Remotion engine lives in:

```text
output/budweiser_apac_story_video/remotion/
```

Common commands:

```bash
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
```

`npm run preview` and `npm run render` automatically call `scripts/sync_assets.sh`, which copies storyboard/timeline JSON, images, audio, SFX, and optional BGM into Remotion.

## QA

After rendering, run ffprobe and extract a contact sheet or key frames. Check:

- video stream and audio stream exist
- 1920x1080, 30fps unless the storyboard intentionally changes it
- no black frames or blank canvas
- subtitles, headlines, keywords, and info cards do not overlap
- narration duration and video duration are close
- years, money, percentages, and ranges are spoken correctly

## Locality

All future generated videos should be produced inside this repository. The old CeibsSalesTouch project is only a historical reference unless the user explicitly asks to inspect it.
