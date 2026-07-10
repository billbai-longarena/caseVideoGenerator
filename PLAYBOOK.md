# Case Video Playbook

This file records durable project defaults. Detailed production steps still live in:

```text
output/budweiser_apac_story_video/VIDEO_PRODUCTION_WORKFLOW.md
output/budweiser_apac_story_video/video_tool_selection.md
```

## Defaults

- Generate all case videos inside this repository.
- If the user names a target duration or duration range, follow it.
- If the user does not name a target duration, generate single-case story videos within 4 to 7 minutes by default.
- Duration rationale: 4 minutes is the floor and squeezes out drama elements (quotes, threat-escalation beats, pre-reveal pauses); 5 to 6 minutes often fits the full narrative skeleton comfortably; 12-minute single-case videos require padding and are a different format.
- Narration pace is about 330 chars/min including pauses (measured across 6 finished videos, 306-357). Budget: target minutes x 330, minus about 60 chars for the fixed column intro/outro.
- Source story md should be 3800-4500 chars for a 5-6 minute video, or 3100-3500 chars for 4 minutes (compression ratio 35-40%). Source files over 4000 chars forced into 4 minutes lose second-tier content (quotes, escalation beats).
- For sales-case videos, use the recurring column name `销售不复杂` unless the user says otherwise.
- Use Azure Speech TTS by default. CosyVoice is a historical fallback only when explicitly requested or Azure is unavailable.
- Unless the user explicitly asks for another voice or gender, use Azure male voice: `zh-CN-Yunxiao:DragonHDFlashLatestNeural`.
- Azure TTS defaults to sentence-cache mode: each sentence is synthesized into `audio/tts_sentences/sentence_XXX.wav`, then assembled into `audio/narration_azure.wav`.
- Sentence-cache mode sends each full sentence to Azure as plain punctuated text. Do not insert in-sentence SSML `<break>` tags by default; let Azure handle comma, colon, pause, and prosody naturally. Unit splitting is only for timeline/storyboard alignment.

## Narration Style

- When a case shares a category with a prior video, vary the narrative lens and presentation.
- For the SaaS transformation case style, emphasize customer transformation, internal challenge, organization politics, team resistance, and implementation friction when the source supports it.
- Chinese narration and subtitles must avoid the contrast pattern `不是……而是……` and close variants such as `不是...而是...`.
- Rewrite those contrasts as direct assertions, causal statements, or two short sentences.

## TTS And Screen Text

- Human-readable narration goes in `narration.txt`.
- Spoken text must go through `tts_text_normalizer.py` before Azure Speech TTS.
- Screen subtitles may keep Arabic numerals for readability; TTS text should use normalized Chinese readings.
- Screen subtitles may keep acronyms such as `IT`, `ERP`, `CRM`, `SKU`, `CIO`, `HR`, and `GMV`.
- TTS must read those acronyms letter by letter. The normalizer should emit spaced letters such as `I T`, `E R P`, and `G M V`.
- For shopping-festival labels such as `618 大促`, screen subtitles may keep digits; TTS text should use digit-by-digit reading such as `六一八大促`.
- Do not use `818 大促` for the SaaS case unless the source or user explicitly reintroduces that date.
- To fix a small TTS issue, regenerate only the affected sentence, for example `--only 12` or `--only 7-9`, instead of rebuilding the whole narration.

## Local Update Workflow

Full Azure narration generation:

```bash
python output/budweiser_apac_story_video/tts_compare/generate_tts.py \
  --engine azure \
  --project output/<project_dir> \
  --gender male
```

Partial TTS fix:

1. Edit `narration.txt`.
2. Find the affected sentence number in `narration.tts.plan.txt` or `audio/tts_sentences/manifest.json`.
3. Regenerate only that cache slot:

```bash
python output/budweiser_apac_story_video/tts_compare/generate_tts.py \
  --engine azure \
  --project output/<project_dir> \
  --gender male \
  --only 12
```

Use `--only 7-9` or `--only 3,8,12` for multiple sentences. Use `--force` only when the same text/voice/rate must be regenerated anyway.

Fast video update:

```bash
cd output/budweiser_apac_story_video/remotion
npm run render:video   # run when the picture layer changed, or once to create a reusable video-only layer
npm run mux:audio      # replace the audio track from the current narration.timeline.json
```

- If only narration/TTS changed, run `npm run mux:audio` and avoid Remotion rerendering.
- If only storyboard/visuals changed, run `npm run render:video`, then `npm run mux:audio`.
- If the final mix must include Remotion BGM ducking or SFX, use `npm run render` for a full render.
- If Azure sounds too rushed, prefer `--rate 0%` or a small `AZURE_TTS_RATE` change before adding manual pauses.

## QA Before Delivery

- Run Remotion typecheck before rendering when project code or storyboard shape changes.
- After rendering, verify video and audio streams with `ffprobe`.
- Run black-frame detection or extract representative frames.
- Confirm subtitles, labels, headlines, keywords, and info cards do not overlap.
- Confirm spoken numbers, years, money, percentages, ranges, acronyms, and promotion labels are correct.
- If only narration changed and the picture layer is still valid, use the fast mux path to replace audio without a Remotion rerender.
