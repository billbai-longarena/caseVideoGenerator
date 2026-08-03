# 竖屏 9:16 手机视频

本文档定义竖屏(1080x1920)手机视频的画布合同、移动最佳实践和与横屏流水线的差异。生产步骤见 `../../workflows/new-vertical-video.md`,任务路由见 `.agents/skills/produce-vertical-video/`。

## 何时使用

- 目标分发是手机全屏竖屏场景:抖音、视频号、快手、YouTube Shorts、Instagram Reels。
- 默认仍是横屏 1920x1080。只有用户明确要求竖屏/手机视频时才用本合同,不要替用户决定。

## 画布声明

- 在 schema-v2 `storyboard_plan.json` 顶层声明 `"canvas": {"width": 1080, "height": 1920}`。省略即横屏 1920x1080。
- 编译器把 canvas 透传进 `rich_storyboard.json`;Remotion 四个合成(CaseVideo/VideoOnly/IntentReview/CoverProof)自动按 JSON 尺寸渲染。目前只支持这两种尺寸,其它尺寸会被编译器拒绝。
- `scripts/case-video` 全部子命令无需新参数:尺寸经 plan → rich_storyboard.json 传导。

## 支持边界(硬约束)

- 竖屏项目**只允许 `editorial` 场景**。共享模板布局(`visualMode: layout/hybrid`)按 16:9 绝对像素调校,竖屏下会被校验器拒绝。用 Visual Beat + 归一化 box 完成全部构图。
- `box`/`region` 归一化坐标天然分辨率无关,优先于 slot。
- 转场三层都可复用;竖屏下 beat `push` 自动变为纵向推镜(手机滑动方向),场景 wipe 的章节大字自动居中重排。
- 不透明文本卡(paper/accent/solid surface)必须绑显式 `box`,并保留 `slot` 供校验器查重;slot 绑定的 opaque 卡会被拒绝。
- 人物 asset layer 必须声明显式预留 `box`;Remotion 在该区域内按 1080×1920 的真实像素计算居中正方形并强制 `contain`,模型不手写头像裁剪。与人物同拍的语义面板也必须有显式 `box`,二者至少保留 0.012 归一化间隙。完整职责合同见 `editorial-component-contract.md`。
- 校验器白名单:beat composition 不含 `custom`,purpose 不含 `reflection`(用 `consequence`/`callback`);每个 beat 必须有 baseAsset 或至少一个 asset 层。

## 移动最佳实践(已固化进引擎)

竖屏分支的具体数值由 `engine/remotion/src/canvas.ts` 与 `VisualBeatTrack.tsx`/`SubtitleBar.tsx`/`BrandBug.tsx` 的 `IS_VERTICAL` 分支实现,改动先改那里再回本文件同步。

- **安全区**:平台浮窗 UI(视频号/小红书/抖音的顶部标签栏、底部头像+文案+按钮栏)会遮挡视频边缘,竖屏内容必须往中间收:顶部 y 320 以上不放任何关键元素(`VERTICAL_SAFE_TOP`),常驻品牌 chip 锚在 `top: 310`(`VERTICAL_CHROME_TOP`);字幕栏悬浮在 `bottom: 400`(`VERTICAL_SUBTITLE_BOTTOM`,栏高约 230px,顶边约 y 1290),所有内容必须收在 y 1240 以上(`VERTICAL_CONTENT_FLOOR`)——`bottom` 车道锚在 `bottom: 680`,`right` 车道下缘不低于 680/790(reserveBottom)。右上角在竖屏下不再渲染 ChapterBadge(平台 UI 遮挡区 + chapter 是导演内部标签)。
- **屏幕文字措辞**:scene 的 `chapter`/`kicker` 会直接渲染上屏(kicker 进左上角 chip 和封面,chapter 在横屏右上角大字和 chapter-circle 转场里)。必须写面向观众的措辞,禁止导演内部术语上屏,如 `钩子`/`悬念`/`铺垫`/`反转`/`高潮`/`收尾`/`尾声` 等;转折类内部节奏标注只写进 `dramaticFunction`/`directorialIntent`。
- **字幕**:栏目 chip 与字幕上下堆叠(标签保持单行,横屏单行规则不变),字号 36/40/44 按长度分档,最长两行;合并阈值 46 字。
- **封面**:hook 标题最大 100px,居中卡片最大 920px 宽,首帧完整可读;移动场景前 3 秒定去留,封面必须直接给冲突或反常结果。封面是短标题 splash:旁白从 0 秒开始,引擎把封面停留钳制在 `COVER_MAX_SECONDS`(2.0s,`engine/remotion/src/canvas.ts`)以内,`cover.throughUnit` 只能再缩短不能延长——不要写跨多个 unit 的标题停留去盖开场正文。
- **文字车道**:64px 侧 margins,952px 内容宽;`left`=`上段`(y 400 起)、`right`=`下段`、`center`=`中段`、`top-left/top-right`=`顶部横带`(y 400 起,品牌 chip 之下)、`inset-*`=900x780 方图位(y 400 起)、`bottom`=字幕上方横带(无 box 的紧凑文本卡锚定车道下缘,不会飘到画面顶边);`triptych` 变三条竖向堆叠卡。文本 caption 42px 起、headline 72px、metric 120px。
- **计数卡**:主值、前后缀和可选差值按实际预留框像素宽度自动拟合,最低字号 42px。`value.from` 只控制动画起点;普通从零计数不会显示增量副本。真正的前后差值用 `showDelta: true` 显式声明,并保持整组单行。
- **构图**:竖屏下非背景型卡片素材的 `portrait-left/right` 自动映射为"图上文下"(图占顶部 56%),`split` 60%,`document-focus`/`evidence-collage` 居中面板;背景型 `baseAsset`(如 `bg-*`、`*-bg-*`、`background-*`)始终全画布铺开,不缩成上半屏,也不与兼容背景轨叠成上下两张图;`read-left/right` 渐变自动改为底部上升渐变。
- **节奏**:12 秒语义空窗上限不变;手机竖屏建议每个 beat 4-8 秒,钩子和反转处更快。

## 竖版图片

- 背景:在 `image_prompts.json` 顶层声明 `"size": "864x1536"`(或在命令行 `--size`)。文件级声明优先于脚本默认值,CLI 显式 `--size` 最高优先。
- `generate_images.py` 在高度大于宽度时,自动把内置 stylePrefix 里的 `cinematic 16:9 composition` 换成竖屏构图短语(主体锚定在中部纵向带、上下留白)。自定义 `stylePrefix` 若不含该短语,会自动前置竖屏短语;`fullPrompt` 原样使用,作者自己保证竖屏构图。
- 竖屏提示词要点:主体放中部纵向三分之一带;极端顶部/底部不放关键内容(会被安全区/字幕吃掉);单主体、少元素,手机小屏容不下横屏式多主体场景。
- 人物肖像仍为 1024x1024 白底半身方形图(`portrait_prompts.json`,中国人声明规则不变);竖屏人物资产在 dialogue/asset 层里以 `fit: contain` 或归一化 box 使用。
- 不要拿横屏背景裁切当竖屏用;竖屏项目一律新生成竖版素材,QA 通过后按既有规则归档入池。

## 校验与 QA 差异

- 校验器新增不变量:竖屏 canvas 出现非 editorial 场景直接报错;contact-sheet 启发式比例窗口已对称化,覆盖竖版拼图。
- `render`/`ready --stage render` 门禁不变;ffprobe 验收值变为 `1080x1920, 30fps, H.264 + AAC`,音画时长差与 blackdetect 规则不变。
- `scripts/extract_video_qa.py` 接触表瓦片按视频方向自动选 270x480;场景/beat 抽帧审查流程不变。
- `publish`/`publish-batch` 分辨率无关,压缩副本保持 1080x1920。

## 时长与栏目

- 栏目、固定开场/结束语、TTS 规范与横屏一致(销售栏目 `销售不复杂`)。
- 竖屏分发甜区通常 1-3 分钟;未指定时长时仍按仓库默认 4-7 分钟写旁白,用户点名竖屏短版时按用户时长控制旁白长度。
