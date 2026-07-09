# Case Video Production Agent Guide

This repository is the dedicated workspace for generating case-story videos with Azure Speech TTS, Remotion, Azure image generation, and ffmpeg QA. Do video work here instead of in `/Users/bill.bai/Desktop/CeibsSalesTouch`.

## Primary Workflow

Before changing or generating video assets, read:

```text
PLAYBOOK.md
output/budweiser_apac_story_video/VIDEO_PRODUCTION_WORKFLOW.md
output/budweiser_apac_story_video/video_tool_selection.md
```

The replicated pipeline is:

```text
case source/materials
-> rewritten narration
-> numeric-normalized TTS script
-> Azure Speech TTS narration wav + narration.timeline.json
-> unit-anchored rich_storyboard.json
-> generated watercolor/background assets
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
- Add this fixed opener to the narration: `这里是《销售不复杂》。帮你揭开销售的魔法秘密，让销售不再复杂。`
- Add this fixed closer to the narration: `这期的《销售不复杂》就到这里。帮你揭开销售的魔法秘密，让销售不再复杂。我们下期再见。`
- Set the subtitle-bar label (`storyboard.subtitleLabel`) to `销售不复杂` so the column name stays visible throughout the video.
- The subtitle-bar label must remain on one line; widen or scale the label area rather than wrapping `销售不复杂`.
- Prefer setting `storyboard.brand` to `销售不复杂` for sales-case videos, keeping per-scene `kicker` for the local chapter label.

## Narration Style

- For Chinese case-video narration and subtitles, do not use the rhetorical contrast pattern `不是……而是……` or close variants such as `不是...而是...`.
- Rewrite those contrasts as direct assertions, causal statements, or two short sentences. Example: `软件上线改变了责任边界。`
- When a case shares a category with a prior video, vary the narrative lens. Avoid repeating the same "sales discovers hidden need, upgrades the solution, wins a larger deal" arc if the source material supports a customer-transformation, internal-resistance, or organization-politics angle.

## TTS Rules

- Human-readable narration goes in `narration.txt`.
- Spoken text must go through `tts_text_normalizer.py` before Azure Speech TTS.
- Screen subtitles may keep Arabic numerals for readability; TTS text should use normalized Chinese readings.
- Azure Speech TTS is the default engine for all future videos. CosyVoice is only a historical fallback unless the user explicitly asks for it.
- Unless the user explicitly asks for another voice or gender, use Azure Speech TTS male voice for generated case videos.
- Preferred Azure voice names: male/default `zh-CN-Yunxiao:DragonHDFlashLatestNeural`; female `zh-CN-Xiaoxiao:DragonHDFlashLatestNeural`.
- Use `AZURE_SPEECH_KEY`/`AZURE_SPEECH_REGION` or `AZURE_TTS_KEY`/`AZURE_TTS_REGION` when available. This workspace also accepts the verified legacy `.env` pair `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`/`AZURE_DOCUMENT_INTELLIGENCE_KEY`; do not print secrets.
- Screen subtitles may keep acronyms such as `IT`, `ERP`, `CRM`, `SKU`, and `CIO`; TTS text must read them letter by letter. The normalizer should emit spaced letters such as `I T`.
- For shopping-festival labels such as `618 大促`, screen subtitles may keep digits; TTS text should use digit-by-digit reading such as `六一八大促`.
- For short enumerations such as `年轻医生培养、学术水平和教学能力`, keep the screen/timeline unit stable but split TTS internally and insert a short inner pause. Do not renumber storyboard units just to fix prosody.
- Use `AZURE_TTS_RATE` when the same voice regenerates too slowly or too quickly; keep it close to the default `+4%` and verify duration against the target video length.
- Generate full narration with the unified TTS entrypoint:

```bash
python output/budweiser_apac_story_video/tts_compare/generate_tts.py \
  --engine azure \
  --project output/medical_device_case_video \
  --gender male
```

The Azure generator writes `audio/narration_azure.wav`, `narration.tts.txt`, `narration.tts.plan.txt`, and `narration.timeline.json`.

## Image Generation

- Azure OpenAI credentials are read from this repository's `.env` first, then from `output/budweiser_apac_story_video/.env` if present.
- Do not print secrets or commit `.env`.
- Use abstract visual prompts. Do not send restricted PDF source text, long excerpts, or sample-video voice data to external providers.
- Keep generated background prompts free of logos, readable text, watermarks, and source-document screenshots.

## Remotion

Remotion lives in:

```text
output/budweiser_apac_story_video/remotion/
```

Common commands:

```bash
cd output/budweiser_apac_story_video/remotion
npm install
npm run typecheck
npm run render
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
