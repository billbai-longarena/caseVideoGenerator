# 质检与交付

## 技术检查

- 视频流和音频流都存在。
- 默认输出为 1920×1080、30fps、H.264 视频和 AAC 音频。
- 文件非空且时长合理。
- 音频时长、timeline duration 和视频时长接近。

## 视觉检查

- 无黑帧、空白画布和未加载素材。
- 精确第 0 帧已显示完整、可读、具有吸引力的封面标题，没有依赖后续入场动画补全。
- 封面完整文案组位于画面几何中心并落在居中 1:1 裁切内；半透明黑色蒙版只包住文字和适量内边距，四周仍能看到明显背景。
- 标题、关键词、信息卡和字幕不重叠。
- 字幕位于安全区，栏目标签保持单行。
- 章节切换清楚，信息按旁白逐步揭示。
- 背景与当前语义一致，连续镜头不存在明显重复构图。
- 所有有效 `annotate` 坐标帧已单独检查，箭头或下划线准确指向有效信息；不存在矩形框或圆圈标注。
- 所有实际人物头像均为正方形白底单人半身像或胸像，清晰度、主体占比、项目画风和角色一致性合格；共享头像的来源与哈希一致。

## 表现力检查

- 关键数字场景使用动画计数或对比条，不是静态大字报。
- 决策网络、权力结构场景出现节点关系图。
- 人物关键原话以对话气泡呈现，并与人物素材同屏。
- 任意连续 12 秒内至少有一次与旁白对应的语义视觉事件；只换镜头、构图、转场或滤镜不算内容变化。
- Layout、Visual Beat 模式和语义工具与内容职责一致，同一信息没有被两个系统重复覆盖。
- 同一 slot 没有同时出现两个面板，对比条与关系节点没有超过单帧可读容量。
- 抽帧覆盖精确第 0 帧、每种语义 layer 首次出现、所有坐标标注和结尾。

## 两阶段视觉 QA

1. 共享布局或图层改动先运行短视频视觉实验室。实验室覆盖全部 layout、composition、语义 layer、长文本和紧凑槽位；逐场景查看 still、短片和 contact sheet，先消除遮挡、越界、跳位和不可读字号。
2. 短视频通过后，再渲染一条 4–7 分钟的真实长案例。长片检查跨场景节奏、素材同步、字幕稳定、模式切换、音画时长和累计渲染稳定性；不能用短片通过替代长片交付 QA。

短视频实验室命令：

```bash
.venv/bin/python scripts/remotion_visual_lab.py --rebuild
scripts/case-video check output/remotion_visual_lab
REMOTION_CONCURRENCY=4 scripts/case-video render-video output/remotion_visual_lab
.venv/bin/python scripts/remotion_visual_lab.py --extract-from output/remotion_visual_lab/video/case_video_video_only.mp4
```

长片语义抽帧命令：

```bash
.venv/bin/python scripts/extract_video_qa.py output/<project>
```

该命令抽取精确第 0 帧、每个 storyboard 场景的稳定帧、最终帧，以及每个 Visual Beat 的稳定帧，并在 `qa/render_qa/` 生成场景和 Visual Beat 两张 contact sheet。等间隔抽帧只能作为补充，不能替代这组语义锚点。

## 渲染前快速评估

调度器、scene 划分或 Visual Beat 改动后，先用现有素材评估，不要立即重做 TTS、生图或整片渲染：

```bash
scripts/case-video build output/<project>
scripts/case-video evaluate output/<project>
scripts/case-video evaluate output/<project> --compare output/<reference-project>
```

`evaluate` 会在 plan 或 timeline 更新后自动同步 `rich_storyboard.json`，并在 `qa/evaluation/` 写入 JSON、Markdown、HTML 和现有图片 contact sheet。直接调用 Python evaluator 时不会自动修改派生文件，而会把过期 storyboard 作为错误报告。

先处理 error，再处理周期模板、局部语义错位、单图承担整场和内容结构重复等 warning。分数用于同一生产体系内的快速回归，不替代关键帧看片；不能通过增加无语义 tint、随机构图、重复文字层或已停用的 `annotate.box` 抬分。需要在自动化中设置门槛时使用 `--fail-under <score>`。

## 分阶段 readiness 门禁

在昂贵步骤前运行统一门禁，而不是等完整渲染后才发现结构或素材问题：

```bash
# 只检查 timeline、storyboard、prompt、provenance 和调度结构。
scripts/case-video ready output/<project> --stage plan

# 增加真实素材、严格 validator、头像像素检查和精确封面证明渲染。
scripts/case-video ready output/<project> --stage render
```

`images` 自动执行 plan readiness，`render` 与 `render-video` 自动执行 render readiness。默认分数门槛分别为 80 和 85；周期调度、模板过度集中、超过 12 秒的语义空档、素材声明缺失、头像不合规、封面偏离中心或蒙版过大属于 blocker。结果和输入哈希写入 `qa/readiness/`。报告只证明记录的那组输入；任何源文件或真实素材变化后都要重新运行。

## 听感检查

- 片头、正文和片尾使用同一 profile。
- 默认交付为女声单人旁白；段落切分、语速和音量保持一致。
- 年份、金额、比例、范围、缩写和活动标签读法正确。
- 无截断、爆音、异常长停顿或句间碎裂。

## 交付门槛

1. 当前输入的 plan readiness 与 render readiness 均通过；没有用调试跳过开关绕过门禁。
2. `scripts/case-video check output/<project>` 通过。
3. Remotion `typecheck` 通过。
4. `scripts/case-video qa output/<project>` 输出符合预期。
5. 共享视觉系统改动已通过短视频实验室，交付项目已通过长视频综合渲染。
6. 已查看 contact sheet、第 0 帧、居中 1:1 封面裁切、结尾帧和所有高风险关键帧。
7. 已完整或重点试听数字密集段与结尾。
8. 已执行 `scripts/case-video publish output/<project>`；项目内压缩副本和 `publish/<主题>/S001_标题.mp4` 均通过流、时长、分辨率、帧率与大小校验。
9. 批量发布时已核对 `publish/manifest.csv` 的栏目、主题文件夹、集数、标题和上传路径，且同一主题文件夹不存在重复集数。

集中发布目录、命名规则和批量命令见 `publishing.md`。
