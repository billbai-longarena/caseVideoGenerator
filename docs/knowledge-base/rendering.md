# Remotion 渲染

## 引擎边界

共享 Remotion 工程位于 `engine/remotion/`。操作者应使用根命令 `scripts/case-video`，不直接绑定引擎内部路径。

## 素材同步

渲染前同步以下项目数据：

- `rich_storyboard.json`
- `narration.timeline.json`
- storyboard 声明的旁白音频
- `images/`、`sfx/` 和可选 BGM

`VIDEO_PROJECT_DIR` 指定目标案例目录。同步后的 `remotion/src/data/generated/` 是构建产物，不手工修改。

## 渲染路径

- 完整渲染：画面、旁白、SFX 和可选 BGM 一次输出。
- 视频层渲染：只重做画面，之后用 ffmpeg mux 最新音轨。
- 只改旁白：优先重建 TTS 后 mux，避免重新生成全部画面。

## 性能与稳定性

- Apple Silicon 使用原生 `arm64` Node 和 Chromium。
- 默认并发为 `6`；不稳定时降到 `4`，资源充足时再试 `8`。
- 切换 Node 架构后删除 `node_modules` 并重新安装。
- 不并行启动同一引擎的多个完整渲染任务，因为共享同步目录会互相覆盖。
- 完整渲染前运行 `typecheck` 和项目 `check`。
