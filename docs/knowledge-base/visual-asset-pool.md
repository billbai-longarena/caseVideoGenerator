# 共享背景素材池

## 目标

背景图采用“新项目新生成、项目本地取用、通过 QA 后归档入池”的架构。共享素材池是已验证叙事插画的归档和可选复用库，不是新视频的默认起点。跨案例复用只在用户明确要求、修订连续性、callback、对照或证据放大等有明确叙事理由时使用；每条视频仍保留自己的分镜、素材副本和来源记录。

素材不靠一个很长的语义文件名管理。文件名只能表达一个维度，且标签变化会迫使重命名。项目使用以下组合：

- SHA-256 内容哈希生成稳定素材 ID，负责去重和追踪同一张图。
- `catalog.json` 保存空间、行为、人物、叙事职责、物件、情绪、行业和画风等多轴标签。
- `views/` 用符号链接提供按场景、行为和画风浏览的人工视图。
- checkout 将选中的图片复制到项目 `images/pool/`，并在 `asset_pool_usage.json` 记录来源和哈希。

## 架构

```text
全部案例文本、分镜、提示词和现有图片
-> taxonomy.json 统一标签语义
-> build：扫描、SHA-256 去重、自动初标、建立引用关系
-> tag_overrides.json：人工看图后对少量误判做可追踪纠偏
-> catalog.json + files/ + views/ + coverage_report.md
-> 新项目：按 Visual Beat 生成项目本地图片并由 image_prompts.json 声明
-> 单图 QA + 成片 QA
-> 再次 build，合格新图回流素材池
-> 可选复用任务：search 按多个维度召回候选
-> 人工检查构图与语义
-> checkout：复制到 output/<project>/images/pool/
-> rich_storyboard.json 引用项目本地路径
```

`build` 只接收可作为最终背景使用的图片。它显式跳过项目内的 `images/characters/`，防止人物头像继承场景标签并污染背景检索；NPC 头像只由 `assets/character-portraits/` 的 `prepare`、`finalize --reviewed`、`audit` 流程管理。`images/management_cutout/` 或路径中带有 `programmatic` 的程序占位图会触发硬错误，不能进入共享池；应删除占位图并生成合格的 AI 叙事插画。

Remotion 不直接读取共享目录。这样单个项目可独立渲染、归档和交付，共享池移动或重建也不会破坏已完成项目。

## 素材归档飞轮与适配门槛

共享池不再作为新项目起点。它的价值是归档、去重、标签治理，以及在明确复用或修订连续性的场景中提供候选。候选图只有同时支持当前叙事语义和最终构图，才算可用；检索有结果但匹配度不足，仍然属于需要新生成的素材。

人工复核按以下四个方面做定性判断，不设置脱离具体案例的固定分数：

- 语义：空间、行为、人物关系和叙事职责与当前 Visual Beat 一致，不能依赖字幕去纠正画面的核心含义。
- 人物：角色画风、文化背景、年龄阶段、性别、权力关系和朝向适合当前场景；同一出场人物保持稳定素材 ID。
- 视觉：视觉家族一致，镜头距离、主体位置、情绪、前后镜头变化和文字安全区可用。
- 质量：没有可读文字、logo、水印、数字伪影、异常肢体、错误人物数量或程序图痕迹。

任一关键项不合格，就为该缺口生成新素材。新图先保存在项目内并由提示词声明；通过单图检查和成片关键帧 QA 后，再进入共享池。成片 QA 还要区分“素材缺陷”和“模板叠加缺陷”：若原图合格但 Remotion 的强调色、滤镜或转场破坏了视觉家族，应修复风格路由，不重生正确素材：

```text
分镜需求
-> 默认按 Visual Beat 生成新图
-> 单图 QA + 成片 QA
-> 背景图 build/audit，人物头像 finalize/audit
-> 校正标签与来源
-> 下一案例在明确复用需求下可检索
```

这形成持续增强的素材飞轮。新增资产必须扩大某类真实业务场景、人物组合或构图能力，不能只为增加数量。背景叙事图进入 `assets/visual-pool/`；可复用 NPC/人物头像进入 `assets/character-portraits/`。两类资产使用独立目录、索引和 QA，项目里的 `images/characters/` 只是人物池 checkout 副本，不参与背景池 build。项目专属姓名、公司和职位留在 Remotion 文本层，不写进共享图片。

## 可穷尽的场景模型

“场景”不能只等同于房间名称。同一个会议室可以承载复盘、谈判、审批或危机响应；同一次销售拜访也可能发生在办公室、工厂、医院或门店。因此分类采用正交多轴，空间场景只负责回答“在哪里”。

当前空间词表包含 24 个业务语义类型和 2 个边界类型：

| 分组 | 空间场景 |
|---|---|
| 企业办公与沟通 | 企业会议室与董事会 `corporate-boardroom`；高管与独立办公室 `executive-office`；开放办公区与普通工位 `open-office`；客服柜台与一线服务点 `service-desk`；前台大厅走廊与候场空间 `reception-corridor`；电话视频与远程协作空间 `remote-communication`；客户公司园区与办公楼 `customer-campus` |
| 生产、行业与运营 | 工厂园区与厂房外景 `factory-campus`；生产线车间与装配现场 `production-floor`；工厂计划控制维护与工程室 `factory-control-room`；仓库库存装卸与配送中心 `warehouse-logistics`；门店超市便利店与渠道终端 `retail-outlet`；医院诊室病区与临床空间 `hospital-clinic`；实验室检测与研发空间 `laboratory-rd`；培训教室课堂与工作坊 `training-classroom`；银行财务资金与交易空间 `finance-treasury` |
| 展示、现场与社交 | 礼堂舞台路演与正式提案空间 `auditorium-presentation`；客户现场巡检施工与户外作业点 `field-site`；机场道路车辆与差旅空间 `transport-travel`；酒店餐厅咖啡与家庭社交空间 `hospitality-social` |
| 编辑性画面 | 文档证据桌面与物件特写 `document-evidence`；地图网络城市与市场全景 `map-network-city`；抽象叙事与组织隐喻 `abstract-editorial`；栏目片头片尾与总结画面 `title-stage` |
| 边界 | 其他专业业务场所 `other-specialized-site`；空间信息不足 `unspecified-setting` |

分镜需求和图片实物采用不同的保守规则。有效分镜若只表达机制、转折或选择而没有明确物理地点，归入 `abstract-editorial` / `metaphor-transition`，因为这就是后续需要制作的视觉类型。`unspecified-setting` 与 `unspecified-activity` 只保留给空白或损坏的分镜记录。图片标签则必须依据实际画面；提示词与成图不一致时，用人工纠偏表修正，不能凭故事上下文补造画面内容。

这套词表的“可穷尽”来自边界值和多轴组合，不代表未来永远不能新增专业场所。新案例先尝试现有空间与行为组合；只有重复出现、无法准确归入现有类型的真实需求才扩展词表。

其他检索轴包括：

- 行为：销售拜访、需求访谈、会议复盘、提案、谈判、审批、签约、培训、排障、采购、生产、库存、远程联络、危机响应等。
- 参与者：销售、客户高管、采购、财务、IT、运营、一线员工、医生、经销商、跨部门团队等。
- 叙事职责：`establish`、`identify`、`evidence`、`explain`、`escalate`、`consequence`、`callback`、`reset`。
- 物件、情绪、行业和视觉家族。

## 当前基线

首次全库盘点覆盖：

- 15 个案例项目。
- 208 个叙事分镜。
- 163 条图片提示词。
- 55 张源图片，SHA-256 去重后仍为 55 张唯一素材。
- 3 个已有视觉家族：销售蓝黄水彩、暖色经理剪影、管理案例亮色水彩旧版。

动态统计、分布和缺口以 `assets/visual-pool/coverage_report.md` 为准。当前报告已经能区分“文本里存在的场景需求”和“素材池实际拥有的图片”，不能把标签命中误当成视觉上一定适用。

## 数据职责

| 文件或目录 | 职责 |
|---|---|
| `assets/visual-pool/taxonomy.json` | 人工维护的受控词表、别名、关键词和项目画风配置 |
| `assets/visual-pool/tag_overrides.json` | 人工视觉复核后的标签替换、增补、移除和说明；以稳定素材 ID 为键 |
| `assets/visual-pool/catalog.json` | build 生成的素材机器索引、哈希、来源、标签和使用记录 |
| `assets/visual-pool/scene_inventory.json` | build 生成的全部分镜需求分类 |
| `assets/visual-pool/coverage_report.md` | build 生成的覆盖统计和待补缺口 |
| `assets/visual-pool/files/` | 按内容哈希去重后的本地二进制素材 |
| `assets/visual-pool/views/` | 按空间、行为和画风建立的人工浏览视图 |
| `output/<project>/asset_pool_usage.json` | 该项目从素材池取用的资产 ID、本地路径和内容哈希 |
| `output/<project>/rich_storyboard.json` | 该视频实际采用什么素材、何时出现以及如何构图 |
| `output/<project>/image_prompts.json` | 只负责该项目新生成图片的可复现提示词 |

`taxonomy.json` 是标签语义源，`tag_overrides.json` 是人工纠偏源，schema-v2 `storyboard_plan.json` 是单条视频的视觉选择与资产 casting 源，`rich_storyboard.json` 是编译后的 render IR。`catalog.json`、分镜清单和覆盖报告都由 build 重建，不手工修改。

## 归档、检索与取用原则

1. 新案例先把分镜需求写成 Visual Beat 视觉简报，并生成项目本地新图。
2. 只有明确复用、修订连续性、callback、对照或证据放大时，才把分镜需求写成“空间 + 行为 + 人物 + 叙事职责 + 画风”的检索简报。
3. 至少使用两个维度检索；只搜“会议”通常过宽。
4. 人工检查主体关系、镜头角度、情绪、文字留白和画风。标签相同不代表构图一定合适。
5. 使用 checkout 复制到项目，不手工引用 `assets/visual-pool/files/`。
6. 跨项目取用是可选策略；同一条视频内反复播放同一图片仍需有 callback、对照、证据放大或明确兜底意图，并标记 `reuse` 或 `allowBackgroundReuse`。
7. 新图通过单图和成片视觉 QA 后回流相应素材池。

常用命令：

```bash
scripts/visual-assets build
scripts/visual-assets stats
scripts/visual-assets audit

scripts/visual-assets search 工厂 产线 --setting 产线 --activity 生产
scripts/visual-assets search 会议 决策 --setting 会议室 --activity 审批 --style 管理者剪影
scripts/visual-assets search 客户 拜访 --activity 销售拜访 --style 销售水彩

scripts/visual-assets checkout <asset-id> output/<project>
```

checkout 会输出可加入 storyboard `visualAssets` 的 JSON 片段，并自动更新 `asset_pool_usage.json`。池中素材在 storyboard 中使用 `origin: "curated"` 和对应的 `poolAssetId`。

## 标签与词表治理

- 优先补充别名和关键词，避免只因措辞不同就新增类别。
- 新空间类型应能跨至少两个案例复用，或有明确的高频生产证据。
- 项目名、客户名和单次剧情细节不进入受控空间词表；它们留在自由文本、行业或对象标签。
- 每张素材必须有一个主场景、一个主行为和一个视觉家族；信息不足时使用明确 fallback，不伪造确定性。
- 自动初标与原图不一致时，在 `tag_overrides.json` 用 `replace`、`add` 或 `remove` 纠偏并写明 `note`；不要改 `catalog.json`，也不要为了纠正单张图污染全局关键词。
- 自动标签必须防止否定句误判，例如 “no conventional boardroom” 不能打上会议室标签。
- build 必须可重复，同一批输入应产生相同目录和目录哈希。
- 词表或分类算法变化后，运行单元测试、全量 build 和 audit，并查看覆盖报告中的异常增减。
