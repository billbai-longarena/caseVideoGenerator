# 视频修订工作流

## 先分类

- 旁白文本、音色、语速、数字读法：走音频路径。
- 字幕、关键词、场景、布局、图片：走视觉路径。
- 两者都改：先完成音频路径，再更新视觉路径。

## 音频路径

1. 修改 `narration.txt`、归一化规则或明确的 TTS 覆盖，并在定稿前完成大模型旁白复核。
2. 局部修复使用 `scripts/case-video tts output/<project> --only <units>`；段落或 profile 改变时完整重跑。
3. 默认使用 `--gender female --single-voice` 保持女声单人旁白；试听并确认新的 `narration.timeline.json`。
4. 若画面不变，执行 `scripts/case-video mux output/<project>`。
5. 若 unit 数量或时长结构改变，继续走视觉路径。

## 视觉路径

1. 根据当前 timeline 修改 `rich_storyboard.json` 或案例专属 storyboard builder；先判断问题来自 scene 划分、Visual Beat purpose、composition、layer 揭示还是素材本身。
2. 按 `reuse-visual-assets.md` 先检索共享池并 checkout 合格候选；只有视觉缺口才更新 `image_prompts.json` 并生图。销售案例保持蓝黄水彩视觉家族，销售管理案例保持本地暖色经理剪影视觉家族，背景不得包含可读文字、数字、字母、logo、水印或 UI/文档截图。
3. 检查主背景与 Visual Beat 素材引用、项目实际文件、`asset_pool_usage.json` 和 `image_prompts.json` 对齐。跨项目复用是默认选项；同一视频内重复同一图必须是显式兜底或有意 callback，不能掩盖图片数量不足。
4. 如果 AI 生图失败，先修复部署、endpoint、prompt 或凭据；不要用 PIL/Canvas/SVG 程序图、流程图、图标集、仪表盘或占位图替代最终背景。
5. 执行 `scripts/case-video check output/<project>`。
6. 执行 `scripts/case-video typecheck output/<project>`。
7. 只改画面时执行 `scripts/case-video render-video output/<project>`，再执行 mux。
8. SFX/BGM 混音也变化时执行完整 render。
9. 新生成图片通过视觉 QA 后执行 `scripts/visual-assets build` 和 `scripts/visual-assets audit`，回流共享池。

## 收尾

- 执行 `scripts/case-video qa output/<project>`。
- 抽查改动前后交界、字幕安全区和受影响数字读法。
- 复盘时执行 `improve-production-system.md`：任务路由或跨阶段守则才改 Skill；稳定步骤改 workflow；可迁移方法改知识库；机器可判定的不变量改 builder/validator/tests；单案例节奏和参数留在项目目录。
