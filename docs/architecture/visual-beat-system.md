# Visual Beat 分层编辑系统

## 目标

Visual Beat 用来把一段旁白拆成若干个有明确叙事职责的视觉拍点。它补充现有的 scene/layout/background 模型，使同一场景可以按 narration unit 切换人物、证据、环境、机制和结果画面，并在一个拍点内组合图片、视频、文字和色彩层。

系统必须同时满足：

- `narration.timeline.json` 继续是唯一时间基线。
- schema-v2 `storyboard_plan.json` 是当前项目的导演 source of truth；`rich_storyboard.json` 是确定性编译出的 render IR。
- 旧项目只写 `backgrounds` 时保持原有渲染结果。
- 新项目由大模型逐场景显式选择 layout、editorial 或 hybrid，并完整声明 Visual Beat 的画面控制。
- 视觉方法允许因案例、素材和叙事视角变化，不把样片的固定秒数写成产品规则。
- adapter 和运行时不按 scene/beat 序号、purpose 或模板数组补创意选择。

## 自由度分层

| 层 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Skill | 识别任务、选择工作流、守住 source of truth 与交付底线、把复盘结论归入正确层 | 不固定镜头数量、停留秒数、构图模板或单案例参数 |
| Workflow | 定义先后顺序、阶段输入输出和质量门 | 不承担 JSON 解析和确定性校验 |
| Knowledge base | 保存可迁移的叙事视觉语法、经验范围和选择方法 | 不把经验范围当成所有案例的硬门槛 |
| Schema / builder / validator | 定义稳定字段、单位换算、引用完整性和机器可判定的不变量 | 不判断某种美学是否永远正确 |
| LLM director plan | 决定本案例的视觉命题、节奏、拍点、构图、素材 casting、文字、镜头、chrome 和例外 | 不把未声明的创意选择留给 adapter 猜测 |
| Case project | 保存导演计划、资产和生成 IR | 不修改共享引擎来偷渡单案例数据 |

## 数据合同

### 顶层素材清单

v2 plan 的 `assets` 是导演阶段的资产 casting 清单，以 `id`、`sceneId`、`role`、`promptIntent` 和可选 continuity 声明“为什么需要这张图”。编译后写入 `rich_storyboard.json.visualAssets`，Visual Beat 通过素材 ID 引用它，避免在多个层里重复路径。

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
- `editorial`：使用 `director-canvas`，由 Visual Beat 和显式 layer 组织画布，隐藏静态业务 layout。
- `hybrid`：播放 Visual Beat 主素材和 tint，同时保留现有业务 layout；Visual Beat 不再承载面板型 layer。

v2 scene 必须显式声明 `visualMode`、`directorialIntent`、scene motion、transition frame count 和 chrome override。没有 `visualBeats` 的历史场景继续回退到原有 `backgrounds` 和 `layout` 行为；省略模式的旧 Visual Beat 数据仍按兼容逻辑读取。

v2 不要求为了填充结构而生成背景图。`assets` 与 `backgrounds` 都可以为空；纯 editorial 场景由从场景首个 unit 开始的 Visual Beat 承担完整画布。旧背景只在明确保留 cue 时继续存在，不能把“每场一张图”当作生产配额。

`director-canvas` 中的可见关键词必须建模为 Visual Beat 的文字 layer，避免关键词组件再次替导演决定位置或样式。`scene.keywords` 只保留两种用途：模型主动选用旧 layout 并委托它安排关键词位置，或用 `display=false` 触发纯音效 cue。v2 中 `display=true` 的关键词必须完整声明入场、表面、颜色、字号、旋转和漂浮；只有 v1 兼容路径保留按序号轮换的旧行为。

### Visual Beat

```json
{
  "visualMode": "editorial",
  "visualBeats": [
    {
      "id": "s02-evidence",
      "atUnit": 4,
      "visualIntent": "evidence",
      "purpose": "evidence",
      "directorialIntent": "先让仓库占满画面，再让周转数字从左侧压入，形成事实挤压人物判断的感觉。",
      "composition": "split",
      "baseAsset": "warehouse-wide",
      "transition": "cut",
      "camera": "push-in",
      "treatment": "crisis",
      "render": {
        "cameraIntensity": 0.7,
        "ambientOpacity": 0.08,
        "vignette": 0.22,
        "overlay": "read-left",
        "transitionFrames": 6,
        "layerEnterFrames": 10,
        "layerExitFrames": 8,
        "layerStaggerFrames": 3,
        "emphasisScale": 1.04,
        "pulse": false,
        "flashbackFrame": false,
        "canvasTone": "dark"
      },
      "layers": [
        {
          "id": "turnover-metric",
          "kind": "counter",
          "slot": "left",
          "label": "库存周转",
          "value": {"to": 82, "suffix": "天"},
          "align": "left",
          "enter": "slide-right",
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
- `visualIntent`：内容职责，如 evidence、relationship、mechanism 或 consequence。
- `purpose`：`establish`、`identify`、`evidence`、`explain`、`escalate`、`consequence`、`callback`、`reset`。
- `directorialIntent`：这一拍的层级、焦点、情绪和可见变化目标。
- `composition`：`full-bleed`、`portrait-left`、`portrait-right`、`split`、`triptych`、`document-focus`、`evidence-collage` 或 `custom`。custom 使用 `baseBox` 与 layer `box` 明确归一化画布区域。
- `render`：显式控制镜头强度、画布、叠层、进出场帧数和节奏；v2 不从 purpose 推导视觉效果。
- `layers`：除 annotate 外必须在 `slot` 与 `box` 中二选一。文字、图片和数据原语的可见样式必须写全，运行时只为历史数据保留兼容默认值。
- `baseAsset`：可选的主素材 ID；没有主素材时，至少一个 asset layer 必须提供画面。
- `transition`：`cut`、`dissolve`、`push`。
- `camera`：`static`、`push-in`、`pull-out`、`pan-left`、`pan-right`、`drift`、`breathe`。
- `treatment`：`natural`、`desaturated`、`blueprint`、`crisis`。
- `render`：显式声明 camera intensity、overlay、vignette、transition/layer frame counts、stagger、emphasis、pulse、flashback frame 和 canvas tone。运行时不得从 purpose 推导这些值。
- `layers`：拍点内的素材、文字或色彩层。

Layer 的 `kind` 为 `asset`、`text`、`tint`、`counter`、`bar-compare`、`network`、`dialogue` 或 `annotate`。所有揭示时间使用 `revealAtUnit`/`exitAtUnit`；位置可以使用语义 slot，也可以用 `box` 直接声明归一化坐标。文字/数据层可显式声明 `surface`、`align`、`enter`、字号、字重、行高和颜色；素材层可声明 `frame`、`fit` 和 box；色彩层使用 `color` 和 `opacity`。这些值均由导演计划决定。

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

### 显式导演控制

v2 中 `purpose` 与 `visualIntent` 只保存语义，不触发隐藏的渲染预设。相机强度、暗角、overlay、pulse、flashback frame、transition frame count、layer entrance/stagger 和 emphasis 都由 `render` 明确声明。layer 的 surface、enter、box、typography 和 media fit 同样明确声明。

旧 v1 数据仍可由兼容运行时应用 purpose 预设和默认 stagger，但这些行为不得进入 v2 编译结果。`drift` 和 `breathe` 仍是可选 camera 原语，是否使用以及强度由导演计划决定。

### Builder 输入

schema-v2 `storyboard_plan.json` 直接使用 1-based narration unit，包括 `atUnit`、`revealAtUnit` 和 `exitAtUnit`。compiler 校验 unit、引用、路径和排序并生成 `rich_storyboard.json`，不做语义调度或美学补全。

scene-relative `offset`、`revealOffset`、`exitOffset` 和自动 purpose 预设只属于 v1 兼容 builder。新项目不得使用它们，也不得把兼容转换误认为导演生成步骤。

## 语义分析辅助

`scripts/visual_beat_planning.py` 可以分析 narration unit、提出语义候选并评估锚点，但它不是 v2 的导演源。最终 scene、beat、composition、asset、camera 和 timing 必须由大模型结合整条叙事显式写入计划；不得让确定性调度器直接产出生产画面。

- 候选携带稳定的 `intent`、文本/数字线索、`anchorPolicy`、表现形式和 layer 数据。`intent` 使用 `context`、`protagonist`、`relationship`、`claim`、`evidence`、`mechanism`、`decision`、`consequence`、`reflection` 等案例职责。
- 场景主张或 governing thought 固定在场景起点；证据、关系、机制和后果候选按当前场景 narration unit 的文字与数字线索寻找语义锚点。
- 分析器可报告局部语义匹配、案例弧线覆盖、表现形式重复和最长语义空档。12 秒是交付上限，不是固定切镜周期，也不是自动插入 beat 的指令。
- 相同数字、关系或主张只能保留一个主要表现形式。不能把同一事实同时排成文字卡、计数器和对比条来伪造丰富度。
- `network` 只表达案例中明确写出的关系。不得为了得到 hub、chain 或 grid 外观自动补连线。
- 内容指纹记录“表达了什么”，调度指纹记录“何时、如何表达”。评估重复度时使用内容指纹，定位锚点漂移时使用调度指纹。

共享分析实现位于 `scripts/visual_beat_planning.py`。它的输出只能作为导演模型的证据或 QA 提示，不能在模型计划之后二次改写计划。

## 无渲染快速评估

`scripts/evaluate_visual_storyboard.py` 只读取现有 `rich_storyboard.json`、`narration.timeline.json` 和项目本地图片，不调用 TTS、生图或 Remotion。它用于在昂贵渲染前发现调度和素材结构问题。

评估分成两个语义尺度：scene alignment 检查一个拍点是否属于当前章节，local alignment 检查它是否排在支持该内容的 narration unit 附近。两者分开报告，避免“整章相关”掩盖局部错位，也避免短句词面不同把正确的章节职责误判为错误。

报告同时检查 intent 覆盖、内容结构重复、周期模板、最长语义空档、单场景主图数量、案例弧线覆盖、旧标注形状和派生文件新鲜度。`storyboard_plan.json` 或 timeline 比 `rich_storyboard.json` 新时，直接运行 evaluator 会报 `stale-derived-storyboard`；通过 `scripts/case-video evaluate` 运行时会先自动重建。

## 运行时分层

渲染顺序从下到上为：

1. 旧 `BackgroundTrack`，提供兼容背景和 Visual Beat 空缺时的兜底。
2. `VisualBeatTrack`，按 unit 播放主素材、构图、镜头运动和拍点内图层。
3. scene 业务 layout；仅 `layout` 和 `hybrid` 模式显示。
4. 品牌、章节、关键词、字幕和全局进度层；v2 按顶层与 scene chrome 开关显示，其中字幕栏必须保持开启。

拍点切换和 layer 揭示都从 timeline unit 解析为 frame。scene enter/exit、scene transition、beat transition 和 layer entrance 使用 v2 显式 frame counts。React 组件不得保存案例专属 unit、路径或秒数，也不得按 scene/beat index 选择 transition 或 motion。

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

1. 旧项目无需立即修改；v1 plan、rich-only storyboard、默认 purpose preset 和 layout fallback 保持可读。
2. 实质性视觉重做先恢复每个 scene 的导演意图，再写 schema-v2 plan；不要把旧 rich storyboard 原样包一层版本号。
3. 同一 v2 项目允许 `layout`、`editorial` 和 `hybrid` 并存；editorial 使用 `director-canvas`。
4. v2 compiler 输出可以保留兼容 background，但不得用它替代导演声明的 asset 与 beat。
5. 当前共享能力不足时扩展 schema、类型、Remotion 原语和测试，而不是把单案例 JSX 写入共享引擎或让 adapter 映射到旧模板。

## 验收标准

### 功能验收

- v2 compiler 能校验 direct 1-based unit、解析引用并忠实生成 render IR；v1 builder 继续支持旧 offset 转换。
- validator 能发现无效素材引用、非法 unit、错误顺序和缺失生成提示词。
- Remotion 能渲染 `layout`、`editorial`、`hybrid` 三种模式。
- `director-canvas` 不添加业务 layout；v2 的 chrome、camera、transition、timing、surface、box 和 typography 按计划生效。
- 对同一 v2 plan 重复编译不会因 scene/beat index 产生不同或新增的创意字段。
- Visual Beat 缺失时，视频继续使用旧 backgrounds 和 layout。
- 图片、视频、文字和 tint layer 均可按 unit 出现，拍点结束由下一拍或 scene 结束自动确定。

### 自动化验收

- builder 与 validator 的兼容、成功和失败路径有自动化测试。
- `scripts/case-video check` 对视觉实验室和代表性长案例通过；旧项目若触发严格视觉错误，应修订后再交付。
- 共享 Remotion `typecheck` 通过。
- 示例案例完整渲染成功，ffprobe 确认 1920×1080、30fps、音视频流存在且时长接近 timeline。
- 代表帧逐 scene 对照 `directorialIntent`，技术通过但层级、焦点、情绪或连续性未实现时不验收。

### 示例视觉验收

- 示例案例至少有一个场景包含三个以上语义拍点。
- 该场景至少使用两类 purpose、两种 composition，并在对应旁白 unit 揭示关键证据。
- 成片无黑帧、空白画布、素材跳失、字幕遮挡或文字越界。
- 旧式 scene 与 Visual Beat scene 的交界自然，品牌栏和字幕栏保持稳定。

这些数量只用于验证本次实现覆盖了核心能力，不是未来案例的固定创作配额。
