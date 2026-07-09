# Case Video Production Notes

Follow `PLAYBOOK.md` and `AGENTS.md` for the full workflow. Additional narration constraint:

- If the user does not name a target duration, generate case videos between 4 and 7 minutes. If the user names a target duration or duration range, follow that specification.
- Unless the user explicitly asks for another voice or gender, use Azure Speech TTS male voice for case videos.
- TTS must read acronyms letter by letter. Keep screen text like `IT` when appropriate, but normalize spoken text to spaced letters such as `I T`.
- For labels such as `618 大促`, keep digits on screen when appropriate and use digit-by-digit TTS reading such as `六一八大促`.
- For Chinese case-video narration and subtitles, do not use the rhetorical contrast pattern `不是……而是……` or close variants such as `不是...而是...`.
- Rewrite those contrasts as direct assertions, causal statements, or two short sentences.
- For case videos in the same sales column, vary the narrative lens so new cases do not repeat the same story arc as previous ones.
