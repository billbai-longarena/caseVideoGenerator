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
- 共享布局或图层改动：先用 `scripts/remotion_visual_lab.py` 生成短场景实验室并逐项抽帧；通过后再渲染代表性长案例验证综合节奏和稳定性。

## 性能与稳定性

- Apple Silicon 使用原生 `arm64` Node 和 Chromium。
- 根脚本根据架构、CPU 和内存选择保守并发；仓库所有者的 10 核、32GB Apple M1 Max 默认 Remotion 并发为 `8`，Azure 生图请求并发为 `3`。不稳定时可将 Remotion 降到 `4`–`6`；生图并发主要受服务配额和请求延迟约束，不随本地 GPU 线性增加。
- 切换 Node 架构后删除 `node_modules` 并重新安装。
- 同一引擎的素材同步、preview、封面证明和 render 由 `scripts/case-video` 的原子锁串行化。若已有存活进程持锁，新任务会显示项目和 PID 后快速失败；失效锁自动清理。不要绕过根脚本直接并行操作共享 `generated/` 目录。
- 完整渲染前运行 `typecheck`、项目 `check` 和 `scripts/case-video ready output/<project> --stage render`。`render` 与 `render-video` 会自动执行 render readiness；它在长渲染前完成严格视觉校验、真实头像检查以及一帧封面证明渲染。
- 编码默认使用 `REMOTION_HARDWARE_ACCELERATION=if-possible`。在 Apple Silicon 上，H.264 可使用 VideoToolbox；Remotion 的 React/Chromium 合成仍主要消耗 CPU 与内存，不能把并发简单按 GPU 核心数放大。
- 长片渲染后运行 `.venv/bin/python scripts/extract_video_qa.py output/<project>`，按场景与 Visual Beat 语义锚点检查画面，不只查看等间隔抽帧。
