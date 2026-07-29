# 新案例视频工作流

## 1. 建立项目

输入：案例材料、目标受众、期望时长和交付要求。

- 在 `output/<project>/` 建立独立案例目录。
- 明确材料使用边界，记录不能外发的内容。
- 用户未指定时长时采用 4–7 分钟。

质量门：项目命名明确，材料边界和目标时长已确认。

## 2. 建立或核验案例模型

- 新写或大幅重构销售案例、销售管理案例时，先执行 `generate-case-story.md`。
- 新写、大幅重构、参数化或合成案例建立 `case_inputs.json`、`case_model.json` 和 `case_story.md`。
- 使用现成完整案例时，至少核验客户问题怎样积累和触发、三类竞争选项、客户决策网络、披露边界以及销售认知怎样更新；需要结构性补写时建立 `case_model.json`。
- 真实案例无法确认的内容保留为未知，不为形成戏剧性自行补齐。

质量门：客户客观真相、客户披露和销售认知已经分开；最终决定能由客户组织结构推出。

## 3. 同期创作标题与旁白

- 依据已确认的材料、`case_model.json` 或 `case_story.md`，提炼主问题、故事矛盾和叙事视角。
- 阅读 `../docs/knowledge-base/narration.md`，设计销售版本与客户真相逐步汇合的揭示顺序。
- 在冷开场、主问题和结尾诊断稳定后选定最终标题，写入 `title.txt`。文件只保留一行最终标题，不写标签、备选项、Markdown 或手工换行。
- 写入 `narration.txt`，用空行控制段落停顿和合成切分；默认不做男女声交替。
- 销售案例加入固定栏目片头、片尾和品牌信息。
- 定稿前由大模型同时复核标题吸引力与事实依据、标题和冷开场承诺的一致性，以及旁白的自然中文、短句、英文术语、缩写连写、数字读法风险和禁用对比句式。

质量门：脚本长度接近目标时长，故事弧线完整，可自然朗读。另须逐项确认：

1. 核心人物在进入冲突前后有 1–2 句身份与关系锚点。
2. 段落揭示顺序与 `case_model.json` 的 `revealPlan` 一致；机制类客户真相都出现在对应销售互动之后，销售出场前只有场面可见事实。
3. 无案例模型术语直出（竞争空间、披露层级、决策网络、信念账本等），关键转折由动作或原话承载。
4. 每个段落至少一个可感细节；无连续两段纯背景或纯解释。
5. `title.txt` 只有一行最终标题；标题表达冲突、问题或反常结果，没有泛化“案例分析”、虚构事实、夸大承诺或与冷开场错位。

任何一项不通过都回到本步骤重写，不带病进入 TTS。

## 4. 生成 TTS 与时间轴

```bash
scripts/case-video tts output/<project> --gender female --single-voice --force
```

- 检查归一化文本、女声单人 profile、数字读法和停顿。
- 必要时修 normalizer、文本标点或段落结构后重跑。

质量门：`narration.timeline.json` 与当前音频一致，重点段试听通过。

## 5. 建立分镜

- 由大模型同时读取 `title.txt`、`narration.txt`、`narration.timeline.json`、案例事实、目标受众和视觉家族，先完成导演判断，再写执行数据。不要从已有 layout 列表或模板轮换开始构思。
- 在 schema-v2 `storyboard_plan.json` 顶层写明视觉命题、节奏、密度、连续性和全局 chrome。资产数量、scene 数量和 beat 数量由叙事职责决定，不采用“一场一图”“每场三拍”或固定切镜周期。
- 以 timeline unit 编号划分连续场景。每个 scene 先写 `dramaticFunction` 和 `directorialIntent`，说明这一段要建立的层级、证据、情绪或关系，再决定 `layout`、`editorial` 或 `hybrid`。
- 模板只是一种能力。固定业务结构确实最清楚时才选择语义 layout；以图片、证据、人物、自由排版和节奏为主时使用 `editorial` + `director-canvas`，由 plan 明确 composition、boxes、camera、treatment、transition、frame counts、layers 和局部 chrome。
- 将 `title.txt` 逐字复制到 plan 的 `cover.title`，不在本步骤另写标题。标题必须在第 0 帧完整可见；封面结束时间写入首场景范围内的 `cover.throughUnit`，不用秒数。若发现标题需要改写，返回第 3 步同时复核旁白承诺。
- **先写视觉剧本，再填 beat**：每个拍点回答“观众此刻看见什么变化、为什么必须在这个 unit 发生”。只有氛围图加静态文字框的拍点是缺陷，不是完成。
- 按信息类型选择 layer kind（合同见 `../docs/architecture/visual-beat-system.md`）：
  - 关键数字和前后对比 → `counter` 或 `bar-compare`，不用纯文字大字报。
  - 决策网络、谁掌握什么 → `network` 节点图。剧本写节点、连线、强调关系和 reveal unit，默认让 `networkLayout: "auto"` 按拓扑与 slot 画幅排布；只有叙事顺序必须固定时才覆盖为 `row`、`column`、`triangle`、`hub` 或 `grid`。
  - 人物原话 → `dialogue` 气泡，绑定人物素材。
  - 图上证据（错配、异常位置）→ `annotate`，只用 `arrow` 或 `underline`。不使用坐标矩形框或圆圈；无法精确定位时改用裁切、`document-focus` 或 `evidence-collage`。
- v2 plan 直接使用 1-based narration unit。运行 deterministic compiler，检查它只做 schema 校验、引用解析、路径处理和字段复制；不得按序号选择 layout、composition、camera、transition 或装饰层。
- 如果已批准的导演意图无法用现有合同表达，先扩展共享 schema 和 Remotion 能力，再回到 plan；不得为了通过构建把想法压成最接近的模板。
- 构建并运行项目检查：

```bash
scripts/case-video build output/<project>
scripts/case-video check output/<project>
```

质量门：plan 的 `cover.title` 与 `title.txt` 完全一致，第 0 帧封面标题完整可读，`cover.throughUnit` 位于首场景；每个 scene 有可审查的 `directorialIntent`；unit 连续覆盖，音频、素材和 layer 引用有效，没有手写秒数替代 unit timing；使用 editorial/hybrid 的场景从 scene 起点就有可见拍点；关键数字、决策网络和关键引语使用了对应的语义 layer；新分镜不含 `box`、隐式方框或 `ring` 标注；`rich_storyboard.json` 与 v2 plan 的导演选择逐项一致，没有编译器补出的模板、卡片、动效或拍点；validator 的表现力警告已逐条处理或说明理由。

## 6. 生成与归档视觉资产

- 先确定一个视觉家族。销售案例默认沿用蓝黄水彩：亮钴蓝/天蓝、镉黄高光、高明暗对比、奶油纸面、透明水彩/水粉叠色、干刷边缘、前景清楚、背景半抽象低细节。FDE（AI 落地）专题默认沿用明亮版蓝黄水彩（`fde-bright-watercolor`）：更高明度的天蓝/浅钴蓝、大面积留白、阳光感暖黄、轻薄叠色、浅色背景。销售管理案例默认沿用本地暖色经理剪影风格：近黑人物剪影、深海军蓝层次、钴蓝、焦橙、灰桃色、奶油到琥珀背光、剪纸/丝网印刷感、干净留白。
- 新项目默认先生成项目本地新背景：按 v2 plan 的资产 casting，以 asset ID 写入 `image_prompts.json`。是否需要新图由导演意图决定，不机械地为每个 scene 或每个 Visual Beat 生成一张图；只使用抽象重写后的场景描述，不把共享池检索作为起点，也不使用池中资产来免除生图。
- 只有用户明确要求复用、修订已有项目需要保持连续性，或分镜设计了 callback、对照、证据放大时，才执行 `reuse-visual-assets.md` 的检索、人工复核和 checkout。池中图必须复制到项目 `images/pool/`，不能直接引用共享池路径。
- 有明确出场人物时，先按角色身份、年龄、朝向、权力关系和画风补充或生成可复用头像规格；已存在头像只在明确复用、修订连续性或有意 callback 时 checkout 到 `images/characters/`。左右对话优先选择相向朝向，人物介绍优先使用正面头像。同一角色在整条案例中保持同一个素材 ID。
- 人物头像统一为正方形、至少 512px、纯白背景的单人半身像或胸像，并明确继承项目视觉家族：销售用蓝黄水彩/水粉语言，销售管理用暖色经理剪影/剪纸丝网印刷语言。所有系列（销售、销售管理、FDE）的头像必须是中国人形象，提示词必须显式写出 Chinese/中国人；render readiness 会把缺中国人声明的头像提示词判为 blocker。提示词必须同时写明白底、半身构图和风格；不得把有人物的叙事背景图当作头像。
- 销售水彩图提示词不要写红色、珊瑚红、铁锈橙、橙红作为风格色；除非案例事实必须出现极小警示色。经理剪影风格允许本地参考里的焦橙和灰桃色背光，但不得生成红色水彩。
- 确认 `storyboard.visualStyle` 已传入 Remotion 风格路由；检查标签、进度条、图表、转场和 Visual Beat 滤镜不会把合格素材改成另一套色系。
- 禁止在背景图里生成可读文字、数字、字母、logo、水印、UI 截图或来源文档截图；数字、金额、百分比和英文缩写放到 Remotion 文本层。
- 最终背景只能使用 AI 生成或人工挑选的叙事插画。AI 生图失败时修配置或停止，不使用 PIL/Canvas/SVG/程序几何图/图标集/流程图/仪表盘/占位图替代。
- 主流程要求 `rich_storyboard.json` 引用与项目实际图片一致：新图由 `image_prompts.json` 覆盖，刻意 checkout 的池中图由 `asset_pool_usage.json` 覆盖。不要因为图片不足让后续 layout 一直播放最后一张图。
- 跨项目复用是可选来源，不是默认策略。同一条视频重复同一张图时，必须有 callback、对照、证据放大或明确兜底意图，并在 scene 或 background cue 上标记 `allowBackgroundReuse`/`reuse`。
- 检查构图变化、文字留白、logo、可读文字、数字伪影和水印。
- 检查 Visual Beat 是否围绕叙事职责轮换，而不是只给同一背景叠加不同标题；需要复用素材时写清 callback 或证据放大的意图。
- 新生成图片通过单图和成片视觉 QA 后回流相应素材池：背景运行 `scripts/visual-assets build` 和 `audit`；新增人物运行 `scripts/character-portraits finalize --reviewed` 和 `audit`。项目内 `images/characters/` 是人物池 checkout 副本，背景 build 必须忽略该目录。

在付费生图前先校验当前分镜、提示词和复用来源：

```bash
scripts/case-video ready output/<project> --stage plan
scripts/case-video images output/<project>
```

`images` 会自动再次执行 plan readiness。门禁失败时先修周期调度、模板集中、长语义空档、封面意图、素材声明或来源，不带病生图。

质量门：plan readiness 通过；所有背景和拍点服务具体语义，画风统一且视觉角色不机械重复；人物头像 ID 和出场关系稳定，白底半身构图和项目画风通过检查；池中图有来源和哈希，新图有提示词；没有程序图或文字数字伪影；模板叠加后的成片仍服从同一视觉家族。

## 7. 预览与渲染

```bash
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video intent-frames output/<project>
scripts/case-video ready output/<project> --stage render
scripts/case-video render output/<project>
```

`render` 会自动再次执行 render readiness。该门禁使用真实素材运行严格 validator，核验头像像素/来源/画风，并渲染精确第 0 帧和透明封面证明层，检查完整文案位于画面几何中心、处在居中 1:1 裁切内，黑色蒙版只覆盖文字且没有吞掉背景。

在完整渲染前，用 `qa/intent-frames/manifest.json` 中的实际 frame ID 逐一对照 plan 的 `directorialIntent`。代表帧必须覆盖每个 scene，并额外覆盖关键 Visual Beat。发现信息层级、视觉焦点、情绪、密度、连续性、素材适配或品牌 chrome 与意图不符时，只允许一次 composition-only 修订并重新生成代表帧；可改构图、裁切、box、slot、同场时序、镜头、treatment、转场和局部 chrome，不得改事实、文案、layout、资产 ID、scene 范围或导演意图。不要在生成的 `rich_storyboard.json` 或 JSX 中做单案例补丁。

质量门：代表帧覆盖所有 scene，`qa/intent-frame-review.json` 通过且引用准确 frame ID；typecheck 与 render readiness 通过，完整渲染成功。

## 8. 质检与交付

```bash
scripts/case-video qa output/<project>
```

- 抽 contact sheet 和关键帧（至少覆盖精确第 0 帧、每种语义 layer 首次出现、所有坐标标注帧和结尾）。
- 建立 intent-to-frame 对照：对每个 scene 记录至少一张代表帧，并判断它是否实现 plan 的 `directorialIntent`。技术合格但意图未落地仍视为失败。
- 完成视觉检查和数字密集段试听。
- 表现力检查：标题、图章与信息卡无重叠；关键数字场景出现动画计数或对比条而非静态文字；每个拍点在其时间窗内有可见变化。
- 记录最终文件、时长、规格和已知限制。

质量门：满足 `docs/knowledge-base/qa-and-delivery.md` 的全部交付门槛。表现力检查不通过时，回到第 5 步修分镜或第 3 步修旁白，修复后重渲；不得以“技术检查已通过”为由交付。
