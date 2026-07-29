# Command Reference

Run all commands from the repository root.

```bash
scripts/case-video build output/<project>
scripts/case-video check output/<project>
scripts/case-video evaluate output/<project>
scripts/case-video ready output/<project> --stage plan
scripts/case-video ready output/<project> --stage render
scripts/case-video tts output/<project>
scripts/case-video images output/<project>
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
scripts/case-video render-video output/<project>
scripts/case-video mux output/<project>
scripts/case-video qa output/<project>
scripts/case-video publish output/<project>
scripts/case-video publish-batch output --pattern 'fde_ep*'
```

After changing a storyboard generator, plan, timeline, or Visual Beat schedule, use the existing local assets for a render-free check first:

```bash
scripts/case-video build output/<project>
scripts/case-video evaluate output/<project>
scripts/case-video evaluate output/<project> --compare output/<reference-project>
scripts/case-video evaluate output/<project> --fail-under 80
```

`evaluate` automatically rebuilds `rich_storyboard.json` when the plan or timeline is newer. Reports are written under `qa/evaluation/`. The evaluator does not call TTS, image generation, or Remotion.

Use readiness as the cross-stage production contract:

```bash
# Storyboard/prompt/provenance gate before paid image generation.
scripts/case-video ready output/<project> --stage plan

# Real-asset, strict-validator, portrait, and exact frame-0 gate before rendering.
scripts/case-video ready output/<project> --stage render
```

The default minimum scores are `80` for plan readiness and `85` for render readiness. Reports and input hashes are written under `qa/readiness/`, so a pass identifies the exact storyboard, timeline, prompt, provenance, and asset state that was checked. `images` automatically runs plan readiness; `render` and `render-video` automatically run render readiness. Override thresholds with `CASE_VIDEO_PLAN_MIN_SCORE` or `CASE_VIDEO_RENDER_MIN_SCORE` only when the delivery contract explicitly requires a stricter value. `CASE_VIDEO_SKIP_READINESS=1` is a focused debugging escape hatch and must not be used for production delivery.

`scripts/case-video` selects conservative local defaults from CPU architecture, core count, and memory. On the repository owner's 10-core Apple M1 Max with 32GB RAM, the defaults are Remotion `8` and Azure image requests `3`. Explicit overrides still take priority:

```bash
REMOTION_CONCURRENCY=8 scripts/case-video render output/<project>
REMOTION_CONCURRENCY=8 scripts/case-video render-video output/<project>
IMAGE_GENERATION_CONCURRENCY=3 scripts/case-video images output/<project> --force --quality medium
scripts/case-video images output/<project> --concurrency 2 --force
```

Asset sync, preview, readiness cover proofs, and renders use one shared generated-data directory. The wrapper therefore acquires an atomic engine lock before any of those operations. A live owner fails fast with its project and PID; a stale lock is removed automatically. This prevents two projects from overwriting each other's synced assets while still allowing independent TTS, planning, evaluation, and bounded image generation to run in parallel. Image concurrency is bounded separately because Azure quota and request latency, rather than local CPU, are usually the limiting factors.

`scripts/case-video check` runs strict visual validation by default. When shared layouts, compositions, or semantic layers change, run the short visual lab before the representative long render:

```bash
.venv/bin/python scripts/remotion_visual_lab.py --rebuild
scripts/case-video check output/remotion_visual_lab
REMOTION_CONCURRENCY=4 scripts/case-video render-video output/remotion_visual_lab
.venv/bin/python scripts/remotion_visual_lab.py --extract-from output/remotion_visual_lab/video/case_video_video_only.mp4
```

After the representative long render, extract semantic QA frames from the real project:

```bash
.venv/bin/python scripts/extract_video_qa.py output/<project>
```

This captures exact frame zero, one stable frame per storyboard scene, the final frame, and one stable frame for every authored Visual Beat. Review both contact sheets under `qa/render_qa/` instead of relying on evenly spaced samples alone.

Shared visual-pool commands:

```bash
scripts/visual-assets build
scripts/visual-assets stats
scripts/visual-assets search <keywords> --setting <setting> --activity <activity> --style <style>
scripts/visual-assets checkout <asset-id> output/<project>
scripts/visual-assets audit
```

Use `search` and visually review candidates before `checkout` only when the task explicitly calls for pool reuse or revision continuity. For new visuals, generate project-local assets first, then use `build` and `audit` after QA to archive accepted assets. The checkout command copies the image into the project and records `asset_pool_usage.json` provenance.

Reusable character-portrait commands:

```bash
scripts/character-portraits search --style sales-watercolor-blue-yellow --gender female --min-age 35 --max-age 50
scripts/character-portraits checkout <portrait-id> output/<project>
scripts/character-portraits audit
```

Portrait checkout copies the selected person into `images/characters/`, records the same provenance manifest, and prints a `visualAssets` object with `role: "person"`. Choose inward-facing portraits for dialogue pairs.

Pass additional TTS options after the project path:

```bash
# Current default delivery: single female narrator.
scripts/case-video tts output/<project> --gender female --single-voice --force
scripts/case-video tts output/<project> --only 12
scripts/case-video tts output/<project> --force
```

Environment overrides:

- `CASE_VIDEO_ENGINE_ROOT`: Reusable engine implementation path.
- `VIDEO_OUTPUT`: Full-render output path.
- `VIDEO_LAYER_OUTPUT`: Video-only output path.
- `REMOTION_CONCURRENCY`: Remotion concurrency. `scripts/case-video` 自适应选择；10 核、32GB Apple Silicon 默认 `8`，一般机器默认 `6`。
- `REMOTION_HARDWARE_ACCELERATION`: H.264 hardware encoding mode, default `if-possible`; use `disable` only for troubleshooting.
- `IMAGE_GENERATION_CONCURRENCY`: Wrapper default for Azure image requests; adaptive default is `3` on a 10-core/32GB Apple Silicon machine and `2` elsewhere.
- `CASE_VIDEO_PLAN_MIN_SCORE`: Plan-readiness score threshold, default `80`.
- `CASE_VIDEO_RENDER_MIN_SCORE`: Render-readiness score threshold, default `85`.
- `CASE_VIDEO_SKIP_READINESS`: Set to `1` only for focused debugging that must reach the underlying image/render command despite a known readiness failure.

On an arm64 Mac, `scripts/case-video` also prefers an installed native arm64 Node over an x86_64 Node running through Rosetta.
- `QA_VIDEO`: Video path checked by the `qa` command.

## Delivery: upload-ready release files

Keep the pipeline-facing master at `video/case_video.mp4`. After QA, use the wrapper to create or validate the ~50 MB project copy, verify both media streams, preserve resolution/frame rate/full duration, and stage a public filename derived from `title.txt`:

```bash
scripts/case-video publish output/<project>
```

The default public name is `S001_标题.mp4`. Three-digit zero padding keeps a 100-video topic sorted correctly through S100. Known project names such as `fde_ep01_*`, `baijiu_ep30_*`, `sales_case02_*`, and `sales_management_case20_*` provide the series and sequence automatically.

Batch staging discovers only projects that contain `video/case_video.mp4`:

```bash
scripts/case-video publish-batch output --pattern 'fde_ep*'
scripts/case-video publish-batch output --pattern 'sales_management_case*' --include-master
```

Uploads are placed directly under `publish/<topic>/`; one topic folder can contain the complete sorted S001-S100 run and contains no manifest files, so it can be opened directly in a website file picker. Optional masters go under `publish/_masters/<topic>/`. `publish/manifest.csv`, `publish/manifest.json`, and `publish/upload-list.txt` remain at the release root and are regenerated as the upload queue. The release directory is Git-ignored and rebuildable. See `docs/knowledge-base/publishing.md` for `publication.json` overrides and collision handling.
