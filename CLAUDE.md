# Case Video Production Notes

**第一原则：具体人物 + 具体事件。** 每个案例旁白必须有至少 3 个有名字的人物和具体的场景事件。关键转折必须绑定人物在哪里、做了什么、说了什么话。不能用"团队觉得""大家认为"等抽象集体表述替代具体人物反应。违反即为缺陷。

Follow `docs/README.md`, the matching file under `workflows/`, and `AGENTS.md` for the full workflow. `PLAYBOOK.md` is a compatibility entry. Additional narration constraints:

- For new narration or video generation, do not read or imitate old generated narration, timelines, storyboards, rendered videos, QA frames, or other completed `output/<project>/` artifacts as examples. Many historical outputs are wrong. Use the production Skill and current source materials; only inspect an existing project's artifacts when the user explicitly asks to revise or audit that project.
- If the user does not name a target duration, generate case videos between 4 and 7 minutes. If the user names a target duration or duration range, follow that specification.
- Unless the user explicitly asks for another voice or gender, use the approved Azure Speech TTS female voice (`zh-CN-Xiaochen:DragonHDLatestNeural`, single narrator) for case videos. The male voice failed earlier listening tests and is only an explicit-request A/B option; see AGENTS.md for the authoritative TTS profile.
- TTS must read acronyms letter by letter. Keep screen text like `IT` when appropriate, but normalize spoken text to spaced letters such as `I T`.
- For labels such as `618 大促`, keep digits on screen when appropriate and use digit-by-digit TTS reading such as `六一八大促`.
- For Chinese case-video narration and subtitles, do not use the rhetorical contrast pattern `不是……而是……` or close variants such as `不是...而是...`.
- Rewrite those contrasts as direct assertions, causal statements, or two short sentences.
- For case videos in the same sales column, vary the narrative lens so new cases do not repeat the same story arc as previous ones.
- When writing or revising narration, immediately create the project folder (`output/<project>/`) and write `narration.txt` to disk. Do not wait for the user to ask; narration must be persisted to a file as soon as it is produced.

## Termite Protocol

This project uses the local blackboard workflow defined in `TERMITE_PROTOCOL.md` v5.1. Before substantive work, run `scripts/field-arrive.sh "<task summary>"` and read `.birth`, `BLACKBOARD.md`, plus any `ALARM.md` or fresh `WIP.md`. Use `signals/active/` for actionable work and `DECISIONS.md` for durable decisions; update the blackboard or a signal before handing work off.

Follow the role boundary selected by the arrival script: scout for research, worker for scoped implementation, soldier for alarms/build failures, nurse for tests and documentation. Human instructions take priority. Keep the runtime state local; `.birth*`, `.field-breath`, `.pheromone`, and `.termite.db*` are ignored. Where this file conflicts with the current video-production requirements, `AGENTS.md` is authoritative.
