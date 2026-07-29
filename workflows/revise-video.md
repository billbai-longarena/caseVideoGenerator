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

1. 先判断项目合同版本。schema-v2 项目只修改 `storyboard_plan.json`，再重建 `rich_storyboard.json`；不得同时手改派生 IR。旧项目可继续修 `rich_storyboard.json`，但实质性视觉重做应优先迁移到 v2。`cover.title` 只能来自 `title.txt`。
2. 把问题分为两类：导演选择问题，或表达能力缺口。前者回到 scene 的 `directorialIntent`、视觉模式、构图、素材 casting、镜头、节奏和层级重新判断；后者扩展共享 schema/Remotion 能力。不得用最近似模板覆盖能力缺口，也不得在 adapter 或案例 JSX 中暗补创意。
3. 需要替换素材时，先按 v2 plan 的资产 casting 和 asset ID 更新 `image_prompts.json`，暂不生图。只有用户明确要求复用、修订需要保留视觉连续性，或分镜有意 callback、对照、证据放大时，才按 `reuse-visual-assets.md` 检索共享池并 checkout 合格候选。销售案例保持蓝黄水彩视觉家族，销售管理案例保持本地暖色经理剪影视觉家族，背景不得包含可读文字、数字、字母、logo、水印或 UI/文档截图。人物头像必须是正方形、至少 512px、白底单人半身像或胸像，并与项目视觉家族一致。
4. 检查主背景与 Visual Beat 素材引用、项目实际文件、`image_prompts.json` 和必要时的 `asset_pool_usage.json` 对齐。跨项目复用是可选的刻意来源；同一视频内重复同一图必须是显式兜底或有意 callback，不能掩盖图片数量不足。
5. 如果 AI 生图失败，先修复部署、endpoint、prompt 或凭据；不要用 PIL/Canvas/SVG 程序图、流程图、图标集、仪表盘或占位图替代最终背景。
6. 存在 v2 plan 时执行 `scripts/case-video build output/<project>`，检查 compiler 只复制/解析显式导演选择，没有按序号补 layout、composition、camera、transition、card 或 beat；再执行 `scripts/case-video evaluate output/<project>`。用现有素材先修正语义错位、最长空档和单图承担整场等问题；不要通过装饰性变化抬分。
7. 执行 `scripts/case-video check output/<project>`。
8. 执行 `scripts/case-video ready output/<project> --stage plan`。它必须在新一轮付费生图前通过；`images` 也会自动执行同一门禁。
9. 需要新图时才执行 `scripts/case-video images output/<project>`，并复核实际素材；不得用生图掩盖调度或结构失败。
10. 执行 `scripts/case-video typecheck output/<project>` 和 `scripts/case-video intent-frames output/<project>`，用 manifest 中的实际 frame ID 把受影响 scene 的代表帧与 `directorialIntent` 逐项对照。技术检查通过但视觉意图未落地时，只允许一次 composition-only 修订并重新审片；可改构图、裁切、box、slot、同场时序、镜头、treatment、转场和局部 chrome，不得改事实、文案、layout、资产 ID、scene 范围或导演意图。
11. 执行 `scripts/case-video ready output/<project> --stage render`，用真实素材核验严格 validator、头像像素/来源/画风，以及精确第 0 帧的居中裁切和蒙版面积；渲染命令也会自动执行同一门禁。
12. 只改画面时执行 `scripts/case-video render-video output/<project>`，再执行 mux。
13. SFX/BGM 混音也变化时执行完整 render。
14. 新生成图片通过视觉 QA 后执行 `scripts/visual-assets build` 和 `scripts/visual-assets audit`，回流共享池。

## 收尾

- 执行 `scripts/case-video qa output/<project>`。
- 执行 `scripts/case-video publish output/<project>`，刷新压缩副本、`S001_标题.mp4` 发布文件和集中清单；标题或集数变化时确认旧发布路径已被清理。
- 抽查改动前后交界、字幕安全区和受影响数字读法。
- 对受影响 scene 保留 intent-to-frame 复核结论；不要把“模板换了”当成导演问题已经解决的证据。
- 复盘时执行 `improve-production-system.md`：任务路由或跨阶段守则才改 Skill；稳定步骤改 workflow；可迁移方法改知识库；机器可判定的不变量改 builder/validator/tests；单案例节奏和参数留在项目目录。
