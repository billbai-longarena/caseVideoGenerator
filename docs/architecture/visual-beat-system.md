# Visual Beat 分层编辑系统

## 目标

Visual Beat 用来把一段旁白拆成若干个有明确叙事职责的视觉拍点。它补充现有的 scene/layout/background 模型，使同一场景可以按 narration unit 切换人物、证据、环境、机制和结果画面，并在一个拍点内组合图片、视频、文字和色彩层。

系统必须同时满足：

- `narration.timeline.json` 继续是唯一时间基线。
- `rich_storyboard.json` 继续是画面编排的 source of truth。
- 旧项目只写 `backgrounds` 时保持原有渲染结果。
- 新项目可以逐场景采用 Visual Beat，不要求一次性迁移全部场景。
- 视觉方法允许因案例、素材和叙事视角变化，不把样片的固定秒数写成产品规则。

## 自由度分层

| 层 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Skill | 识别任务、选择工作流、守住 source of truth 与交付底线、把复盘结论归入正确层 | 不固定镜头数量、停留秒数、构图模板或单案例参数 |
| Workflow | 定义先后顺序、阶段输入输出和质量门 | 不承担 JSON 解析和确定性校验 |
| Knowledge base | 保存可迁移的叙事视觉语法、经验范围和选择方法 | 不把经验范围当成所有案例的硬门槛 |
| Schema / builder / validator | 定义稳定字段、单位换算、引用完整性和机器可判定的不变量 | 不判断某种美学是否永远正确 |
| Case project | 决定本案例的节奏、拍点、构图、素材、文字和例外 | 不修改共享引擎来偷渡单案例数据 |

## 数据合同

### 顶层素材清单

`rich_storyboard.json.visualAssets` 是可选的素材清单。存在 Visual Beat 时，拍点通过素材 ID 引用它，避免在多个层里重复路径。

```json
{
  "visualAssets": [
    {
      "id": "warehouse-wide",
      "type": "image",
      "src": "images/sales_watercolor/02.png",
      "role": "context",
      "origin": "generated"
    }
  ]
}
```

稳定字段：

- `id`：项目内唯一。
- `type`：`image` 或 `video`。
- `src`：相对项目根目录的本地路径。
- `role`：`context`、`person`、`evidence`、`document`、`map`、`metaphor`、`texture` 之一。
- `origin`：`generated` 或 `curated`。
- `credit`、`license`：人工挑选素材需要时填写，不参与渲染。

### 场景模式

每个 scene 可选声明 `visualMode`：

- `layout`：沿用背景加现有 LayoutRouter，由 layout 独占业务语义面板。
- `editorial`：播放 Visual Beat，保留品牌、章节和字幕层，隐藏静态业务 layout。
- `hybrid`：播放 Visual Beat 主素材和 tint，同时保留现有业务 layout；Visual Beat 不再承载面板型 layer。

没有 `visualBeats` 的场景始终回退到原有 `backgrounds` 和 `layout` 行为。存在 `visualBeats` 但省略 `visualMode` 时，运行时按 `editorial` 处理；新项目应显式声明模式。

### Visual Beat

```json
{
  "visualMode": "editorial",
  "visualBeats": [
    {
      "id": "s02-evidence",
      "atUnit": 4,
      "purpose": "evidence",
      "composition": "split",
      "baseAsset": "warehouse-wide",
      "transition": "cut",
      "camera": "push-in",
      "treatment": "crisis",
      "layers": [
        {
          "id": "turnover-metric",
          "kind": "text",
          "slot": "left",
          "label": "库存周转",
          "text": "82天",
          "variant": "metric",
          "revealAtUnit": 4
        }
      ]
    }
  ]
}
```

拍点字段：

- `id`：项目内唯一。
- `atUnit`：拍点开始的 narration unit。结束点由下一拍或 scene 结束推导。
- `purpose`：`establish`、`identify`、`evidence`、`explain`、`escalate`、`consequence`、`callback`、`reset`。
- `composition`：`full-bleed`、`portrait-left`、`portrait-right`、`split`、`triptych`、`document-focus`、`evidence-collage`。
- `baseAsset`：可选的主素材 ID；没有主素材时，至少一个 asset layer 必须提供画面。
- `transition`：`cut`、`dissolve`、`push`。
- `camera`：`static`、`push-in`、`pull-out`、`pan-left`、`pan-right`、`drift`、`breathe`。
- `treatment`：`natural`、`desaturated`、`blueprint`、`crisis`。
- `layers`：拍点内的素材、文字或色彩层。

Layer 的 `kind` 为 `asset`、`text`、`tint`、`counter`、`bar-compare`、`network`、`dialogue` 或 `annotate`。所有揭示时间使用 `revealAtUnit`/`exitAtUnit`；位置使用语义 slot，如 `canvas`、`left`、`right`、`center`、`inset-left`、`inset-right`、`top-left`、`top-right`、`bottom`。文字层可声明 `label`、`text` 和 `variant`，素材层引用 `asset`，色彩层使用 `color` 和 `opacity`。

### 语义数据 layer

五种语义 layer 让画面直接演绎信息，替代纯文字大字报：

| kind | 用途 | 必填字段 | 可选字段 |
| --- | --- | --- | --- |
| `counter` | 数字滚动动画，可带增减箭头 | `value: {to}` | `value.from/suffix/prefix/decimals`、`label`、`text`、`deltaTone: good\|bad\|neutral` |
| `bar-compare` | 横向对比条，逐条生长 | `bars: [{label, value}]` | 每条 `max/suffix/tone/revealAtUnit`、`label`、`text` |
| `network` | 节点关系图，节点弹入、连线描画 | `nodes: [{id, label}]`（≥2） | 节点 `sub/asset/emphasis/revealAtUnit`；`links: [{from, to, label?, revealAtUnit?}]`；`label`；`networkLayout: auto\|row\|column\|triangle\|hub\|grid` |
| `dialogue` | 人物对话气泡，逐字显示 | `speaker`、`text` | `tail: left\|right`（气泡尾指向说话人一侧） |
| `annotate` | 叠加在底图上的方向性证据定位 | `region: {x,y,w,h}`（0–1 相对全幅） | `shape: arrow\|underline`、`text`、`color` |

选择规则：关键数字和前后对比用 `counter`/`bar-compare`；决策网络与权力结构用 `network`；人物原话用 `dialogue` 并与 portrait asset layer 配对；指认图上具体证据用 `annotate`。新分镜只允许 `arrow` 和 `underline`。旧 `box`、省略 shape 的隐式方框和 `ring` 只保留兼容读取，不再渲染、不计为语义视觉变化，并产生 validator 警告。坐标标注必须抽取对应帧核对，目标边界不稳定时改用裁切、document-focus 或 evidence-collage。这些信息不允许退化成 `text` 大字报。

`network` 默认使用 `networkLayout: "auto"`。运行时同时读取节点、连线拓扑和 slot 画幅：矮宽区域优先横排；唯一高连接度节点优先作为 hub；三个非中心节点使用三角形；四个节点使用网格。只有叙事必须固定阅读方向时才显式指定布局。节点顺序表达内容顺序，不再承担隐含坐标；超过四个节点时拆成多个 beat，并用 `revealAtUnit` 逐步建立关系。

### purpose 驱动的渲染预设

`purpose` 不再只是策划标注，运行时按 purpose 应用默认渲染：`evidence` 聚焦暗角加快揭示；`escalate` 相机加速加色调脉冲；`consequence` 强调数字层；`callback` 加闪回边框降饱和；`identify` 收窄相机突出人物。显式字段可覆盖预设。同一拍点内多个 layer 自动按 purpose 节奏级联入场（stagger），入场后有轻微悬浮，不再整拍冻结。`drift` 和 `breathe` 用于长停留静态插画的微动，幅度低于 `push-in` 和 `pan-*`，适合保持画面活性而不制造新的叙事转折。

### Builder 输入

`storyboard_plan.json` 可以用相对 scene 起点的 `offset`、`revealOffset` 和 `exitOffset`。共享 builder 把它们转换成 `atUnit`、`revealAtUnit` 和 `exitAtUnit`；`bar-compare` 的 `bars`、`network` 的 `nodes`/`links` 内的 `revealOffset` 同样被转换。生成后的 `rich_storyboard.json` 不保留手写秒数。

## 语义候选与调度

自动分镜分成“候选生成”和“时间调度”两层。候选先描述可见内容，再决定落在哪个 narration unit；不得按场景序号、拍点序号或模板数组取模轮换构图。

- 候选携带稳定的 `intent`、文本/数字线索、`anchorPolicy`、表现形式和 layer 数据。`intent` 使用 `context`、`protagonist`、`relationship`、`claim`、`evidence`、`mechanism`、`decision`、`consequence`、`reflection` 等案例职责。
- 场景主张或 governing thought 固定在场景起点；证据、关系、机制和后果候选按当前场景 narration unit 的文字与数字线索寻找语义锚点。
- 调度器联合考虑局部语义匹配、全场景契约、案例弧线覆盖、表现形式去重和最长语义空档。12 秒是交付上限，不是固定切镜周期。
- 相同数字、关系或主张只能保留一个主要表现形式。不能把同一事实同时排成文字卡、计数器和对比条来伪造丰富度。
- `network` 只表达案例中明确写出的关系。不得为了得到 hub、chain 或 grid 外观自动补连线。
- 内容指纹记录“表达了什么”，调度指纹记录“何时、如何表达”。评估重复度时使用内容指纹，定位锚点漂移时使用调度指纹。

共享实现位于 `scripts/visual_beat_planning.py`。案例生成器可以提供候选和少量明确关系，但不应复制调度算法。

## 无渲染快速评估

`scripts/evaluate_visual_storyboard.py` 只读取现有 `rich_storyboard.json`、`narration.timeline.json` 和项目本地图片，不调用 TTS、生图或 Remotion。它用于在昂贵渲染前发现调度和素材结构问题。

评估分成两个语义尺度：scene alignment 检查一个拍点是否属于当前章节，local alignment 检查它是否排在支持该内容的 narration unit 附近。两者分开报告，避免“整章相关”掩盖局部错位，也避免短句词面不同把正确的章节职责误判为错误。

报告同时检查 intent 覆盖、内容结构重复、周期模板、最长语义空档、单场景主图数量、案例弧线覆盖、旧标注形状和派生文件新鲜度。`storyboard_plan.json` 或 timeline 比 `rich_storyboard.json` 新时，直接运行 evaluator 会报 `stale-derived-storyboard`；通过 `scripts/case-video evaluate` 运行时会先自动重建。

## 运行时分层

渲染顺序从下到上为：

1. 旧 `BackgroundTrack`，提供兼容背景和 Visual Beat 空缺时的兜底。
2. `VisualBeatTrack`，按 unit 播放主素材、构图、镜头运动和拍点内图层。
3. scene 业务 layout；仅 `layout` 和 `hybrid` 模式显示。
4. 品牌、章节、关键词、字幕和全局进度层。

拍点切换和 layer 揭示都从 timeline unit 解析为 frame。React 组件不得保存案例专属 unit、路径或秒数。

## 校验边界

以下结构问题始终是硬错误：

- 素材或拍点 ID 重复。
- 素材路径越出项目目录、文件不存在或类型不支持。
- 拍点不按 unit 递增、超出 scene，或 editorial/hybrid 场景第一拍没有覆盖 scene 起点。
- 拍点、layer 引用不存在的素材。
- layer 的揭示/退出 unit 超出 scene、早于当前拍点，或退出不晚于揭示。
- Visual Beat 出现秒数型 timing 字段。
- `origin=generated` 的图片没有对应 `image_prompts.json` 声明。

`scripts/case-video check` 默认启用严格视觉校验，以下生产质量问题会使检查失败：

- 连续拍点的主素材和语义 layer 完全相同；改变 purpose、camera、composition、transition、treatment、slot 或 timing 不能把相同内容变成新拍点。
- 三个以上拍点中 `callback` 占比超过 35%，或 callback 只是机械重复同一内容。
- 任意两个语义视觉事件间隔超过 12 秒。语义事件包括主素材变化、layer 揭示/退出，以及 bar、node、link 的分步揭示。
- `hybrid` 使用 tint 之外的 Visual Beat layer；业务语义应放进 layout props，或把场景切换为 `editorial`。
- 同一拍点内，同一 slot 的面板 layer 在同一时间激活；需要改 slot 或设置不重叠的 reveal/exit unit。
- 单个 `bar-compare` 超过 4 条、单个 `network` 超过 4 个节点，或有效 `annotate` 区域越出画布。

以下保留为质量提示，仍需人工复核：

- 单个拍点停留过长。
- 单个拍点超过约 8 秒且没有任何内部 layer 揭示。
- 同一场景连续三个以上拍点只有 text/tint 层，没有语义数据层或素材变化。
- 连续拍点重复相同素材、purpose、role 或 composition。
- 一段重要证据只有装饰性画面，没有证据或机制层。
- 长段落只有慢推背景，没有视觉角色切换。

提示阈值可以随视频类型和目标节奏调整。样片中约 6 秒一次强变化、1–3 秒一次局部揭示可作为策划参考；严格校验的 12 秒上限是防止长时间无内容变化的交付底线，不是机械换图节拍。

## 迁移策略

1. 旧项目无需修改；`visualAssets` 和 `visualBeats` 都是可选字段。
2. 优先迁移信息密度高、人物关系复杂或需要证据揭示的场景。
3. 同一项目允许 `layout`、`editorial` 和 `hybrid` 并存。
4. 迁移后仍保留每个 scene 的 legacy background，作为兼容兜底和转场底色。
5. 确认视觉语法稳定后，再逐步扩展 composition，而不是把单案例 JSX 写入共享引擎。

## 验收标准

### 功能验收

- 共享 builder 能把 plan 中的 Visual Beat offset 转成绝对 unit，并保持旧 plan 输出兼容。
- validator 能发现无效素材引用、非法 unit、错误顺序和缺失生成提示词。
- Remotion 能渲染 `layout`、`editorial`、`hybrid` 三种模式。
- Visual Beat 缺失时，视频继续使用旧 backgrounds 和 layout。
- 图片、视频、文字和 tint layer 均可按 unit 出现，拍点结束由下一拍或 scene 结束自动确定。

### 自动化验收

- builder 与 validator 的兼容、成功和失败路径有自动化测试。
- `scripts/case-video check` 对视觉实验室和代表性长案例通过；旧项目若触发严格视觉错误，应修订后再交付。
- 共享 Remotion `typecheck` 通过。
- 示例案例完整渲染成功，ffprobe 确认 1920×1080、30fps、音视频流存在且时长接近 timeline。

### 示例视觉验收

- 示例案例至少有一个场景包含三个以上语义拍点。
- 该场景至少使用两类 purpose、两种 composition，并在对应旁白 unit 揭示关键证据。
- 成片无黑帧、空白画布、素材跳失、字幕遮挡或文字越界。
- 旧式 scene 与 Visual Beat scene 的交界自然，品牌栏和字幕栏保持稳定。

这些数量只用于验证本次实现覆盖了核心能力，不是未来案例的固定创作配额。
