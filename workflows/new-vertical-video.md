# 竖屏 9:16 手机视频工作流

从已有标题旁白到竖屏(1080x1920)手机成片。与 `new-case-video.md` 共用同一条流水线,本工作流只列竖屏差异与必须执行的竖屏步骤;未提及的阶段(TTS、QA、发布)按横屏工作流原文执行。

适用:用户明确要求手机竖屏/9:16/抖音/视频号/Shorts 视频。画布合同与最佳实践数值见 `../docs/knowledge-base/vertical-mobile-video.md`。

## 1. 建立项目

- 项目目录 `output/<project>_video/`,内部结构与横屏一致。
- 标题进 `title.txt`,旁白进 `narration.txt`,规则与横屏相同(第一原则、禁句、 acronym 连写、开场结束语)。
- 竖屏短版需求在此阶段确认目标时长;未指定仍按仓库默认 4-7 分钟。
- 先运行 `scripts/case-video preflight output/<project> --stage content`。未通过前不进入 TTS；它会锁定标题形状、FDE 固定开收场、禁用对比句、acronym 连写和 `case_inputs.json`。

## 2. 生成 TTS 与时间轴

- 与横屏完全一致:`scripts/case-video tts output/<project> --gender female --single-voice --force`。
- `narration.timeline.json` 仍是唯一计时基准。

## 3. 建立竖屏分镜

- 先写 schema-v2 `storyboard_plan.json`,顶层必须声明 `"canvas": {"width": 1080, "height": 1920}`。
- **全部场景 `visualMode: editorial`**;不使用 layout/hybrid(校验器会拒绝)。构图用 Visual Beat 的 composition、slot 或归一化 `box`。
- 按手机竖屏构思画面:图上文下、单主体、大字号、短句分层;每个 beat 4-8 秒,语义空窗不超过 12 秒。
- dialogue 层按 Skill 规则绑定人物肖像资产(中国人、白底、半身、1024x1024);竖屏对话气泡带圆形头像。对话和 bottom 车道由引擎留出字幕安全区(内容下限 y 1410),不要用 box 把内容压到字幕栏上。
- 编译:`scripts/case-video build output/<project>`,先跑严格 `check`，再跑 `evaluate` 与 `ready --stage plan`。若两个相邻 beat 只有 camera/composition 变化而没有新的语义签名，删除或补充真实的证据/人物/标注，不要用镜头变化伪造节拍。
- 带 `dialogue`/`counter` 的 beat 先预留独立区域；不要继续叠加通用标题层，人物、对白框、计数卡之间必须保留 validator 要求的间距。
- 运行 `scripts/case-video preflight output/<project> --stage plan`，把竖屏画布、editorial/director-canvas、背景 cue、beat asset、purpose 白名单和竖版图片尺寸一次性锁住。

## 4. 生成竖版视觉资产

- `image_prompts.json` 顶层声明 `"size": "864x1536"`,背景全部竖版新生成;人物肖像走 `portrait_prompts.json`(1024x1024)。
- 提示词主体锚定中部纵向带,顶部/底部不放关键内容;禁止文字、数字、logo 的规则不变。
- 执行 `scripts/case-video images output/<project>`(自动过 plan 门禁);先 `--limit 1` 验证尺寸与风格再全量。
- 图片全量生成后，先检查 `rich_storyboard.json` 的每个 visual asset 都有项目内文件，再进入意图帧；不要等整片渲染到中后段才发现资源缺失。
- 不横图竖裁;QA 通过后按 `reuse-visual-assets.md` 归档入池。

## 5. 预览与渲染

- `typecheck` → `intent-frames` → 人工逐场景审查并写入 `qa/intent-frame-review.json` → `ready --stage render` → `preflight --stage render` → `render`。
- intent-frame 审查必须确认:封面首帧大字可读、字幕栏不越界不压字、文字车道在安全区内、图上文下构图成立。
- `preflight --stage render` 是全量渲染前的硬门禁：它检查所有背景/肖像文件、尺寸、资产角色、intent-frame review 和 manifest。没有 pass review 不得启动长渲染。
- Remotion 渲染必须通过 `scripts/case-video render` 获得隔离 workspace；不要直接在共享 `engine/remotion/public` 中渲染或手动同步。

## 6. 质检与交付

- ffprobe 验收:`1080x1920, 30fps, H.264 + AAC`,音画时长差与 blackdetect 规则同横屏。
- 场景/beat 接触表抽帧人工审查;竖版瓦片自动适配。
- 交付:`scripts/case-video publish output/<project>`,压缩副本保持 1080x1920。
