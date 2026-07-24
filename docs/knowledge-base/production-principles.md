# 生产总原则

## 唯一数据源

- 新写或大幅重构的销售案例以 `case_inputs.json` 记录来源边界和初始参数，以 `case_model.json` 作为客户真相、披露、销售认知和最终决定的叙事事实源。
- `case_model.json` 不承担口播、时间或画面职责；它生成或约束 `case_story.md` 和 `narration.txt`，不能替代 timeline 与 storyboard。
- `title.txt` 是文章与视频标题的唯一编辑源，必须与 `narration.txt` 同期创作和复核。
- `narration.txt` 是人类可读旁白源。
- `narration.timeline.json` 是唯一时间基准。
- `rich_storyboard.json` 是第 0 帧封面布局、场景、字幕、关键词、背景和音频声明的唯一分镜源；其中 `cover.title` 必须逐字复制 `title.txt`，不能在分镜阶段另写标题。
- `assets/visual-pool/taxonomy.json` 是跨案例视觉标签语义源；`catalog.json` 是由现有图片和项目引用重建的共享检索索引。
- `asset_pool_usage.json` 只记录单个项目从共享池取用的素材来源和哈希，不能替代 `rich_storyboard.json` 的画面选择与 unit 编排。
- `image_prompts.json` 记录项目新生成图片的可复现提示词；从素材池取用的图片由 `asset_pool_usage.json` 覆盖。
- TTS 专用文本、计划和时间轴属于生成物，应由共享工具重建。

## 默认规格

- 用户未指定时长时，单案例视频默认 4–7 分钟。
- 默认 1920×1080、30fps，除非分镜明确改变规格。
- 每条新视频第 0 帧默认显示带吸引力标题的封面。标题在旁白创作阶段写入 `title.txt`，应提出冲突、问题或反常结果，避免泛化的“案例分析”和源材料不支持的夸张承诺；封面持续到首场景内的 `cover.throughUnit`。
- 销售案例默认栏目为 `销售不复杂`，并在旁白、`brand` 和 `subtitleLabel` 中保持一致。
- 销售案例固定片头：`这里是销售不复杂，用销售和管理经典案例帮您揭开销售的秘密。`
- 销售案例固定片尾：`这期的《销售不复杂》就到这里。帮你揭开销售的魔法秘密，让销售不再复杂。我们下期再见。`

## 时间与数据规则

- 使用 `units`、`atUnit` 和 `...AtUnits` 表达语义出现时机。
- 封面结束同样使用 narration unit，不在 Remotion 中写固定秒数。
- 不在 Remotion 组件中硬编码已有 JSON 数据。
- 只改 `title.txt` 时重建 storyboard 并重跑 readiness；旁白未变时无需重建 TTS。
- 改旁白后先重建音频和 timeline，再调整分镜。
- 场景 unit 区间必须连续覆盖全部旁白单元。

## 视觉资产规则

- 新案例默认先按当前分镜生成项目本地新图，不以共享素材池检索作为起点。视觉修订需要换图时也优先生成新素材；只有用户明确要求复用、修订需要保留连续性，或分镜有意 callback、对照、证据放大时才 checkout 池中素材。
- 共享素材必须 checkout 到项目 `images/pool/`；Remotion 和 storyboard 不直接依赖共享池路径。
- 跨项目复用是可选的刻意来源，不是填补新场景的默认策略。同一条视频内重复同一图片仍需有 callback、对照、证据放大或明确兜底意图。
- 新图通过单图和成片 QA 后重新 build/audit 入池，使后续案例可以检索和复用。
- 图上证据标注只使用箭头或下划线；矩形框和圆圈都已停用。坐标不可靠时改用裁切或证据聚焦构图。

## 合规与安全

- 限制性 PDF 只在本地阅读和提炼，不向外部服务发送长段原文。
- 生图提示词只包含抽象重写后的视觉描述。
- 不使用样片人声做未经授权的音色克隆。
- 不打印、记录或提交 `.env` 和密钥。
