# LLM 导演优先的视频架构

## 为什么要改

旧链路把“创意自由”写成原则，却把真正的画面选择分散在案例脚本、adapter、固定 layout、purpose 预设和 Remotion 全局叠层里。模型只交付有限字段，后续代码再按位置或索引补 composition、motion、transition 和卡片。结果可以通过结构校验，但导演意图在执行途中被模板平均化。

新架构的目标不是减少约束，而是把约束放到正确层：事实、单位、路径和安全区保持确定性；审美、叙事、层级、节奏和镜头选择由大模型完整声明，并被运行时忠实执行。

## 五层合同

| 层 | 主要产物 | 责任 | 禁止行为 |
| --- | --- | --- | --- |
| 事实与时间 | `case_model.json`、`narration.txt`、`narration.timeline.json` | 提供事实边界、口播和唯一时间基线 | 不替视觉层做模板选择 |
| LLM 导演 | schema-v2 `storyboard_plan.json` | 决定视觉命题、scene 意图、资产 casting、模式、构图、镜头、节奏、layer、chrome | 不依赖 adapter 猜测未声明创意 |
| 确定性编译 | `rich_storyboard.json` | 校验、解析 unit/引用/路径并复制声明 | 不轮换模板、不补拍点、不按索引赋动效、不增加装饰 |
| Remotion 执行 | React 组件与媒体资源 | 将 IR 按帧渲染，提供可组合的原语和语义 layout | 不用隐藏默认值改写导演选择 |
| 意图复核 | 代表帧、contact sheet、QA 记录 | 比较成片与 `directorialIntent`，发现层级、焦点、情绪和连续性偏差 | 不用元素数量或总分代替观看判断 |

## 模板是能力，不是起点

- `layout` 适合确实需要固定业务结构的场景，例如明确的比较、流程或关系框架。
- `editorial` 使用 `director-canvas`，让模型通过 composition、boxes、asset/text/data layers 和 timing 直接组织画布。
- `hybrid` 只在固定结构仍是主角、素材承担辅助语境时使用。
- 模型可以选择重复一种构图，也可以每场不同；判断依据是叙事职责和连续性，不是“多样化配额”。
- 资产数量由导演计划决定。既不强制一场一图，也不把每个 beat 生图当成质量指标。

## v2 计划必须显式表达什么

顶层需要视觉命题、节奏、密度、连续性策略和全局 chrome。每个 scene 需要戏剧功能、`directorialIntent`、单位范围、`visualMode`、layout 或 `director-canvas`、scene motion、transition frame count 和 chrome。每个 beat 需要 purpose、composition、可选自定义 boxes、camera、treatment、transition、transition frame count、layer entrance frame count、layer 数据和局部 chrome。

字段显式化的目的不是让模型填更多表格，而是防止执行层在模型不知情时做导演决定。计划只应声明画面真正需要的元素；没有叙事作用的标签、卡片和动画应删除。

背景可见性也是导演决定。使用 `bg-*`、`*-bg`、`background-*` 等背景型 baseAsset 时，v2 计划必须把 `canvasTone` 设为 `transparent`，并用 tint、overlay、box、glass/none 文本、裁切和镜头来组织可读层级；不透明画布和未 boxed 的纸面/实色文本卡会把背景替换成通用信息卡，属于合同偏差而不是可接受的渲染风格。

## 能力升级规则

当模型提出的合理画面无法用现有合同表达时：

1. 确认这是可迁移的表达能力，而不是单案例像素补丁。
2. 扩展 schema、类型、Remotion 原语和最小回归测试。
3. 让模型在 v2 plan 中显式选择新能力。
4. 编译器继续只做确定性转换。

不得在 adapter 中把新意图映射成旧模板，也不得在案例目录写 JSX 来绕过合同。这样会重新形成不可见的第二导演。

## 一次到位的工作闭环

1. 模型先完成视觉命题和 scene 级导演判断，再展开 beat。
2. 在付费生图前确定性编译、校验 plan 与 IR 是否逐项一致，并批准精确的视觉合同 revision。
3. 依据已批准合同生成项目资产；该步骤不得反向改写 scene、beat 或导演意图。
4. 用真实资产渲染 `CaseVideoIntentReview` 代表帧，每个 scene 至少覆盖一帧，其余名额按 Visual Beat 均匀抽样。
5. 多模态审片模型逐帧对照 `directorialIntent`，复核信息层级、焦点、情绪、密度、连续性、素材适配和 chrome，并必须引用实际 frame ID。
6. 如需修复，只允许一次 composition-only 修订：可改构图、裁切、box、slot、同场时序、镜头、treatment、转场和局部 chrome；不得改事实、文案、layout、资产 ID、scene 范围或导演意图。修订后重新渲染并复核。
7. 实际像素通过意图审片后再做最终视觉批准，随后进入完整渲染和交付 QA。

视觉合同批准与最终视觉批准是两个不同检查点。前者防止在结构未稳定时付费生图；后者确认真实素材经 Remotion 执行后的像素确实实现了合同。内部生图和受限编排修订不得清除前者，也不得导致批准后重复生图。

“一次到位”不是不允许迭代，而是让第一轮就包含完整导演决策，并把迭代集中在可见意图偏差上，而不是渲染后才发现 adapter 和模板替模型做了决定。

## 兼容边界

v1 plan、scene-relative offset、purpose 驱动预设和旧 layout 默认值只保留为历史项目兼容路径。新项目不得依赖这些隐式行为。迁移项目时先恢复 scene 的导演意图，再转写为 v2 plan；不要把旧 rich storyboard 原样包装成 v2。
