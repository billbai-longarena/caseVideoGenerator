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
