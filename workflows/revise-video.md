# 视频修订工作流

## 先分类

- 旁白文本、音色、语速、数字读法：走音频路径。
- 只改标题：修改 `title.txt`，复核它与冷开场和主问题的承诺一致，再走视觉路径重建封面；旁白不变时无需重跑 TTS。
- 字幕、关键词、场景、布局、图片：走视觉路径。
- 两者都改：先完成音频路径，再更新视觉路径。

## 音频路径

1. 修改 `narration.txt`、归一化规则或明确的 TTS 覆盖；若叙事承诺变化，同步修改 `title.txt`，并在定稿前完成标题与旁白的大模型复核。
2. 局部修复使用 `scripts/case-video tts output/<project> --only <units>`；段落或 profile 改变时完整重跑。
3. 默认使用 `--gender female --single-voice` 保持女声单人旁白；试听并确认新的 `narration.timeline.json`。
4. 若画面不变，执行 `scripts/case-video mux output/<project>`。
5. 若 unit 数量或时长结构改变，继续走视觉路径。

## 视觉路径

1. 根据当前 timeline 修改 `storyboard_plan.json`、`rich_storyboard.json` 或案例专属 storyboard generator；`cover.title` 只能来自 `title.txt`。先判断问题来自 scene 划分、Visual Beat intent/purpose、语义锚点、表现形式还是素材本身。存在 plan 时不要同时手改派生的 rich storyboard。
2. 需要替换素材时，先按当前 Visual Beat 更新 `image_prompts.json`，暂不生图。只有用户明确要求复用、修订需要保留视觉连续性，或分镜有意 callback、对照、证据放大时，才按 `reuse-visual-assets.md` 检索共享池并 checkout 合格候选。销售案例保持蓝黄水彩视觉家族，销售管理案例保持本地暖色经理剪影视觉家族，背景不得包含可读文字、数字、字母、logo、水印或 UI/文档截图。人物头像必须是正方形、至少 512px、白底单人半身像或胸像，并与项目视觉家族一致。
3. 检查主背景与 Visual Beat 素材引用、项目实际文件、`image_prompts.json` 和必要时的 `asset_pool_usage.json` 对齐。跨项目复用是可选的刻意来源；同一视频内重复同一图必须是显式兜底或有意 callback，不能掩盖图片数量不足。
4. 如果 AI 生图失败，先修复部署、endpoint、prompt 或凭据；不要用 PIL/Canvas/SVG 程序图、流程图、图标集、仪表盘或占位图替代最终背景。
5. 存在 plan 时执行 `scripts/case-video build output/<project>`，再执行 `scripts/case-video evaluate output/<project>`。用现有素材先修正周期模板、语义错位、最长空档和单图承担整场等问题；不要通过装饰性变化抬分。
6. 执行 `scripts/case-video check output/<project>`。
7. 执行 `scripts/case-video ready output/<project> --stage plan`。它必须在新一轮付费生图前通过；`images` 也会自动执行同一门禁。
8. 需要新图时才执行 `scripts/case-video images output/<project>`，并复核实际素材；不得用生图掩盖调度或结构失败。
9. 执行 `scripts/case-video typecheck output/<project>`。
10. 执行 `scripts/case-video ready output/<project> --stage render`，用真实素材核验严格 validator、头像像素/来源/画风，以及精确第 0 帧的居中裁切和蒙版面积；渲染命令也会自动执行同一门禁。
11. 只改画面时执行 `scripts/case-video render-video output/<project>`，再执行 mux。
12. SFX/BGM 混音也变化时执行完整 render。
13. 新生成图片通过视觉 QA 后执行 `scripts/visual-assets build` 和 `scripts/visual-assets audit`，回流共享池。

## 收尾

- 执行 `scripts/case-video qa output/<project>`。
- 抽查改动前后交界、字幕安全区和受影响数字读法。
- 复盘时执行 `improve-production-system.md`：任务路由或跨阶段守则才改 Skill；稳定步骤改 workflow；可迁移方法改知识库；机器可判定的不变量改 builder/validator/tests；单案例节奏和参数留在项目目录。
