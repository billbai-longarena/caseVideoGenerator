# Case Video Generator

用于把案例材料生产为中文案例故事视频的本地工作区。默认流水线为：案例改写 → Azure Speech TTS → unit 时间轴 → JSON 分镜 → 视觉资产 → Remotion → ffmpeg/ffprobe QA。

## 从这里开始

- 项目知识库：`docs/README.md`
- 新视频工作流：`workflows/new-case-video.md`
- 视频修订工作流：`workflows/revise-video.md`
- Agent Skill：`.agents/skills/produce-case-video/SKILL.md`
- 目录与职责：`docs/architecture/repository-layout.md`

## 统一命令

```bash
scripts/case-video check output/<project>
scripts/case-video tts output/<project>
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
scripts/case-video qa output/<project>
```

查看完整命令：

```bash
scripts/case-video
```

## 环境安装

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

cd output/budweiser_apac_story_video/remotion
npm install
```

根目录 `.env` 用于本地 Azure 凭据并已被 Git 忽略。不要打印或提交密钥。

## 当前架构说明

共享 TTS 和 Remotion 引擎目前仍位于 `output/budweiser_apac_story_video/`。这是历史实现位置；新流程通过 `scripts/case-video` 访问它，具体迁移边界见 `engine/README.md`。
