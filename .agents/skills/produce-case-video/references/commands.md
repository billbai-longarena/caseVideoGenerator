# Command Reference

Run all commands from the repository root.

```bash
scripts/case-video check output/<project>
scripts/case-video tts output/<project>
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
scripts/case-video render-video output/<project>
scripts/case-video mux output/<project>
scripts/case-video qa output/<project>
```

For visual-heavy Remotion renders, set concurrency explicitly when the machine has enough headroom:

```bash
REMOTION_CONCURRENCY=8 scripts/case-video render output/<project>
REMOTION_CONCURRENCY=8 scripts/case-video render-video output/<project>
```

The default is `6`. Do not start multiple full renders for the same shared Remotion engine at once because asset sync uses a shared generated-data directory.

Shared visual-pool commands:

```bash
scripts/visual-assets build
scripts/visual-assets stats
scripts/visual-assets search <keywords> --setting <setting> --activity <activity> --style <style>
scripts/visual-assets checkout <asset-id> output/<project>
scripts/visual-assets audit
```

Use `search` and visually review candidates before `checkout`. The checkout command copies the image into the project and records `asset_pool_usage.json` provenance.

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
- `REMOTION_CONCURRENCY`: Remotion concurrency, default `6`.
- `QA_VIDEO`: Video path checked by the `qa` command.
