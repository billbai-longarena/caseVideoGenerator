# 小红书竖屏案例视频工作流

从选题到竖屏(1080x1920)小红书首发成片。共用 `new-vertical-video.md` 的竖屏画布合同、`../docs/knowledge-base/editorial-component-contract.md` 的模型/组件职责合同和 `new-case-video.md` 的 TTS/渲染/QA 流水线；本工作流只列小红书差异步骤。

适用：用户明确要求小红书视频、2-3 分钟竖屏短版案例视频、或女性领导力系列选题的小红书版生产。

## 0. 选题与矩阵校验

输入：选题编号或选题蓝图（如 `input/women_leadership_100/series_blueprint.md`）。

- 确认本集的矩阵编码（角色/阶段/挑战/理论/弧线）和行业、人物年龄。
- 检查与已完成案例的防重复规则：角色(A)+挑战(C)+弧线(E) 三项不得完全相同。
- 确认所属主题季(S1-S10)的核心理论是否已被覆盖。
- 读取该集的选题 md（如 `input/women_leadership_100/S01_选题_01-10.md`），提取人物设定和梗概。

质量门：矩阵编码无冲突，理论配额未超限，行业去重通过。

## 1. 建立项目与跨模型制作参数预案

- 项目目录 `output/<project>_video/`，命名规则 `women_leadership_XX_video`（XX 为两位数集号）。
- 明确目标：小红书版 2-3 分钟（500-750 字旁白），可选同期产出长版 4-5 分钟。
- 竖屏 9:16 (1080x1920)。
- 按 `.agents/skills/produce-xiaohongshu-video/references/production-parameters-contract.md` 创建 `production_parameters.txt`。
- 策划模型在该文件一次性写入标题候选、hook、剧情需要的具名人物、核心事件、转折行为、结果、理论金句、CTA、旁白预算、画布、节奏、画面家族、图片尺寸与数量、TTS 参数和待确认项。3 分钟以下可用 2 位具名人物，不为凑数添加第三人。
- 仅做预案时设为 `APPROVAL_STATUS: WAITING_FOR_APPROVAL` 并立即停止，不创建 `title.txt`、旁白、TTS、图片提示词、分镜或任何媒体资产。
- 执行模型必须先读取该文件；只有状态为 `APPROVED`、没有任何 `PENDING` 值时，才能进入第 2 步。

```bash
# 策划阶段：只检查结构
python .agents/skills/produce-xiaohongshu-video/scripts/validate_production_parameters.py output/<project>/production_parameters.txt

# 执行阶段：强制要求用户已批准且无待定项
python .agents/skills/produce-xiaohongshu-video/scripts/validate_production_parameters.py output/<project>/production_parameters.txt --require-approved
```

质量门：项目目录和预案已建立；矩阵、人物事件、标题方向、理论金句、视觉家族、时长、声音与交付参数均已获得用户确认。

## 2. 同期创作标题与旁白

### 标题

- 读取已批准的 `production_parameters.txt`，把其中锁定的 `PRIMARY_TITLE` 原样写入 `title.txt`。
- 采用小红书"具体场景 + 反常结论"公式，不超过 20 字。
- 示例："她被提拔那天没人鼓掌"、"第一次开除人她也哭了"。
- 标题必须带情绪冲突但不标题党，能独立成为小红书封面大字。
- 写入 `title.txt`，只保留一行最终标题。

### 旁白

阅读选题梗概和理论锚点，按以下小红书版结构写旁白：

```
00:00-00:05  钩子：最尖锐的冲突瞬间（一句话，直接扔进冲突现场）
00:05-00:30  人物 + 困境快速建立
00:30-01:15  冲突场景：具体事件（谁在哪里说了什么）
01:15-01:50  转折：关键行为或对话
01:50-02:20  结果 + 行为改变
02:20-02:35  理论金句点题（一句话升华）
02:35-02:45  结束语 + 引导收藏/评论
```

#### 旁白要求

- **字数**：500-750 字（不含开场/结束固定语）。
- **人物**：按剧情需要选择。3 分钟以下至少 2 个具名人物即可；关键事件确实需要独立的现场反应、证据或对手线时再增加第三人。
- **场景**：至少 1 个核心场景事件，绑定具体地点、行为、对话。
- **理论植入**：1 句理论金句，15 秒以内，自然嵌入故事结尾。
- **前 3 秒**：绝对不做自我介绍、栏目介绍、主题预告。直接冲突现场。
- **结尾**：引导收藏/评论（"你遇到过吗？""收藏这条，下次遇到时翻出来看"）。
- **禁止**：抽象集体表述（"团队觉得""大家认为"）、`不是……而是……` 句式、老师讲课式理论讲解。
- **信息节奏**：每 20-30 秒一个信息锚点。

#### 栏目固定语

- 开场白和结束语待栏目名称确定后设定（与「销售不复杂」区分）。
- 当前暂不使用固定开场白，以冲突直入开场。

写入 `narration.txt`。

#### 长版差异（可选同期产出）

如果同时产出长版（4-5 分钟），在小红书版基础上扩展：
- 人物增加到 3 个有名字的人物。
- 场景增加到 2 个以上。
- 理论植入扩展到 30 秒理论段落。
- 增加情境铺垫和下集预告。
- 写入 `narration_long.txt`。

质量门：

1. 旁白字数在 500-750 字区间（小红书版）。
2. 前两句话必须是冲突场景（非介绍、非铺垫）。
3. 至少 2 个有名字的人物，至少 1 个具体场景事件；人物数量服务剧情，关键反应全部落实到具体人物。
4. 理论金句不超过两句话。
5. 结尾有互动引导语。
6. 不含禁用句式和抽象集体表述。

## 3. 生成 TTS 与时间轴

与现有流水线一致：

```bash
scripts/case-video tts output/<project> --gender female --single-voice --force
```

- 女声 `zh-CN-Xiaochen:DragonHDLatestNeural`。
- 检查归一化文本、数字读法、停顿。
- 验收：总时长应在 2:00-3:00 之间（小红书版）。超出则回第 2 步删减旁白。

质量门：`narration.timeline.json` 时长在目标区间，重点段试听通过。

## 4. 建立竖屏分镜

- 按 `new-vertical-video.md` 的全部竖屏规则建立 `storyboard_plan.json`。
- 顶层声明 `"canvas": {"width": 1080, "height": 1920}`。
- 全部场景 `visualMode: editorial`。

### 小红书分镜特殊要求

- **封面首帧**：hook 标题用情绪痛点大字（最大 100px），确保手机小屏可读。封面图选最具冲突感的场景作为背景；栏目角标按 plan 从第 0 帧常驻，但不能抢过 hook 主标题。
- **封面衔接**：封面独占其存续帧，底层正片 chrome、字幕和正文不得穿透；结束帧由共享 `coverEndFrame()` 决定，底层第一拍不得重复封面句子。
- **信息密度**：2-3 分钟内每个 beat 4-6 秒（比标准竖屏更快）。
- **理论金句帧**：在理论点题段落设计一个视觉突出的金句卡片帧（大字号、强对比），方便用户截屏收藏。
- **结尾帧**：收藏引导 + 话题标签可视化。

### 模型创意与组件规范分工

- 模型声明叙事目的、素材身份、文案、unit、镜头、转场和人物/信息区的显式 `box`；不得依赖编译器按序号补布局或轮换组件。
- Remotion 在人物预留区内确定像素正方形、居中和 `contain`，并统一控制白底、边框与阴影；模型不得用手调 crop 修补头像框。
- 与人物同时出现的语义面板必须有显式 `box`，并与人物保留至少 `0.012` 归一化间隙；校验失败回到 plan 改构图。
- 关键叙事文字使用浅色字配有边界的深色 `glass`/`solid` 卡片；水彩背景上不得直接压裸露正文。
- 开场在有数字或结果落差时，优先用计数、对比条或证据变化表达，不能只做连续文字淡入。

```bash
scripts/case-video build output/<project>
scripts/case-video check output/<project>
scripts/case-video ready output/<project> --stage plan
```

质量门：plan readiness 通过，封面首帧大字可读，金句帧突出，beat 节奏 4-6 秒。

## 5. 生成竖版视觉资产

- `image_prompts.json` 顶层声明 `"size": "864x1536"`。
- 女性领导力新视频和修订视频统一使用 `women-leadership-five-color-watercolor`；执行模型不得恢复已废弃的红色水彩家族。
- 人物肖像走 `portrait_prompts.json`（1024x1024，中国人，白底半身）。
- 先 `--limit 1` 验证风格再全量。

```bash
scripts/case-video images output/<project>
```

质量门：竖版背景无横图竖裁，画风统一，无文字/数字/logo 伪影。

## 6. 预览与渲染

```bash
scripts/case-video typecheck output/<project>
scripts/case-video intent-frames output/<project>
scripts/case-video ready output/<project> --stage render
scripts/case-video render output/<project>
```

intent-frame 审查额外确认：
- 封面大字手机尺寸可读。
- 第 0 帧栏目角标按计划显示；封面结束前后无标题/正片重影。
- 每个人物首次出现时，头像为像素正方形、完整 `contain`，且不与语义面板相撞。
- 所有关键正文均为浅色字深色承载面，没有直接压在水彩背景上的低对比文字。
- 理论金句帧视觉突出。
- 字幕栏不压内容。

质量门：代表帧覆盖所有 scene，1080x1920 30fps H.264+AAC，时长 2:00-3:00。

## 7. 质检与交付

```bash
scripts/case-video qa output/<project>
scripts/case-video publish output/<project>
```

- ffprobe 验收：1080x1920, 30fps, H.264+AAC。
- 接触表抽帧人工审查。
- 发布副本保持 1080x1920。
- 发布路径：`publish/女性领导力/WL-XXX_标题.mp4`。

### 小红书发布配套（人工步骤）

发布到小红书时配套准备：

| 配套元素 | 要求 |
|---------|------|
| 封面 | 从视频首帧或金句帧导出，加大字痛点标题（不超过 12 字） |
| 标题 | 同 `title.txt`，可微调为小红书风格 |
| 正文 | 3-5 行摘要 + 理论金句 + 引导词 |
| 话题标签 | #女性领导力 #职场女性 #职场成长 + 当期理论标签 |
| 评论区 | 置顶评论放理论延伸或下集预告 |
| 发布时间 | 工作日 12:00-13:00 或 21:00-22:00 |

质量门：满足交付门槛，发布配套清单已准备。

## 8. 矩阵更新

- 完成后更新 `series_blueprint.md` 中对应理论和行业的"已使用"计数。
- 每完成 10 集做一次矩阵覆盖率复盘。
