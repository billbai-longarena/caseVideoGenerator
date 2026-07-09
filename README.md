# Case Video

Dedicated local workspace for case-story video generation with CosyVoice, Remotion, Azure image generation, and ffmpeg QA.

Default duration: if no target duration is named, generate between 4 and 7 minutes. If a target duration or range is named, follow it.

Start here:

```bash
cd output/budweiser_apac_story_video/remotion
npm install
npm run typecheck
npm run render
```

Detailed workflow:

```text
output/budweiser_apac_story_video/VIDEO_PRODUCTION_WORKFLOW.md
output/budweiser_apac_story_video/video_tool_selection.md
```

Generate narration with the default Azure male voice:

```bash
python output/budweiser_apac_story_video/tts_compare/generate_tts.py \
  --engine azure \
  --project output/medical_device_case_video \
  --gender male
```

Use `--gender female` only when a female voice is explicitly requested.

The copied `.env` lives at the repository root and is ignored by git.
