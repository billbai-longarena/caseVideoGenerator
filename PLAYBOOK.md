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

## QA Before Delivery

- Run Remotion typecheck before rendering when project code or storyboard shape changes.
- After rendering, verify video and audio streams with `ffprobe`.
- Run black-frame detection or extract representative frames.
- Confirm subtitles, labels, headlines, keywords, and info cards do not overlap.
- Confirm spoken numbers, years, money, percentages, ranges, acronyms, and promotion labels are correct.
