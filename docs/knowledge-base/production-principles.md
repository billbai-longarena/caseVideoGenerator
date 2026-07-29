# 生产总原则

## 唯一数据源

- 新写或大幅重构的销售案例以 `case_inputs.json` 记录来源边界和初始参数，以 `case_model.json` 作为客户真相、披露、销售认知和最终决定的叙事事实源。
- `case_model.json` 不承担口播、时间或画面职责；它生成或约束 `case_story.md` 和 `narration.txt`，不能替代 timeline 与 storyboard。
- `title.txt` 是文章与视频标题的唯一编辑源，必须与 `narration.txt` 同期创作和复核。
- `narration.txt` 是人类可读旁白源。
- `narration.timeline.json` 是唯一时间基准。
- 当前项目以 schema-v2 `storyboard_plan.json` 作为视觉导演源稿：由大模型明确视觉命题、scene 意图、素材 casting、构图、镜头、节奏、图层和 chrome。`cover.title` 必须逐字复制 `title.txt`，不能在分镜阶段另写标题。
- `rich_storyboard.json` 是从 v2 plan 确定性编译出的 Remotion render IR，不是第二份编辑源。编译器只做校验、unit/引用/路径解析和字段复制，不增加任何美学判断。没有 v2 plan 的历史项目可继续以 rich storyboard 为源，直到迁移。
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

## 导演权与执行边界

- 大模型负责导演判断：视觉命题、每场戏的戏剧功能和 `directorialIntent`、信息层级、资产数量与复用、视觉模式、构图、camera、treatment、transition、frame counts、layer 和局部 chrome。
- schema、adapter、builder 和 validator 负责确定性工作：验证合同、解析 unit 与引用、复制声明、检查路径和不变量。它们不得按 scene/beat 序号轮换模板，不得自动补三拍、卡片、装饰、转场或相机运动。
- Remotion layout 是可选能力，不是生产模板。固定业务结构最清楚时使用语义 layout；以图片、人物、证据和自由排版为主时使用 `director-canvas` 与显式 composition/boxes/layers。
- 若合同无法表达已经确定的导演意图，先扩展共享能力，再生成 render IR。不能因为现有模板有限就把创意压成最近似的布局。
- 质量闭环必须比较 `directorialIntent` 与代表帧。门禁分数、元素数量、模板变化和动效数量都不能替代这一判断。
- 付费生图前批准精确视觉合同；真实素材完成后再渲染覆盖全部 scene 的代表帧，按 frame ID 做多模态意图审片，最后批准实际像素。这两个批准点不能合并。
- 审片后的自动修复最多一次，只能调整构图、裁切、空间、同场时序、镜头、treatment、转场和局部 chrome；事实、文案、layout、资产 ID、scene 范围和 `directorialIntent` 属于不可变内容。

## 视觉资产规则

- 新案例默认先按当前分镜生成项目本地新图，不以共享素材池检索作为起点。视觉修订需要换图时也优先生成新素材；只有用户明确要求复用、修订需要保留连续性，或分镜有意 callback、对照、证据放大时才 checkout 池中素材。
- 共享素材必须 checkout 到项目 `images/pool/`；Remotion 和 storyboard 不直接依赖共享池路径。
- 跨项目复用是可选的刻意来源，不是填补新场景的默认策略。同一条视频内重复同一图片仍需有 callback、对照、证据放大或明确兜底意图。
- 新图通过单图和成片 QA 后重新 build/audit 入池，使后续案例可以检索和复用。
- 图上证据标注只使用箭头或下划线；矩形框和圆圈都已停用。坐标不可靠时改用裁切或证据聚焦构图。

## 客户定制视频的品牌与故事分离

- 为客户（幼儿园、企业等）定制的品牌视频系列，客户品牌名和 slogan 只出现在固定栏目开场和结尾。
- 故事正文必须是脱敏的第三方案例：人物、学校、机构全部使用虚构名字，与客户品牌无关联。
- 故事聚焦行为、场景和成长范式本身，让观众通过内容产生认同，避免写成客户的自我推广。
- 故事中引用的老师、园长、管理者等角色均为虚构，不挂客户机构实际人员姓名或职务。

## 合规与安全

- 限制性 PDF 只在本地阅读和提炼，不向外部服务发送长段原文。
- 生图提示词只包含抽象重写后的视觉描述。
- 不使用样片人声做未经授权的音色克隆。
- 不打印、记录或提交 `.env` 和密钥。
