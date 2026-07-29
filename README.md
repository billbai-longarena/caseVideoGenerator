# Case Video Generator

把案例材料生产为中文案例故事视频的本地工作区。仓库内置的默认流水线是：案例改写 → Azure Speech TTS → unit 时间轴 → JSON 分镜 → AI 视觉资产 → Remotion → ffmpeg/ffprobe QA。

本仓库不提供云服务账号、密钥、额度或代理服务。使用者需要自行选择并开通 Azure、字节/火山引擎或其他合规服务，并自行承担实名、计费、配额、数据区域和内容合规责任。

## 5 分钟快速上手

### 1. 准备本机环境

需要 Python 3、Node.js/npm、ffmpeg 和 ffprobe。安装项目依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

cd engine/remotion
npm install
cd ../..
```

只有运行可部署服务器时才需要额外安装 `requirements-server.txt`。

### 2. 配置自己的云服务

复制环境变量模板，不要把真实密钥提交到 Git：

```bash
cp .env.example .env
```

内置的一键命令目前使用 Azure：

- TTS：填写 `AZURE_SPEECH_KEY` 和 `AZURE_SPEECH_REGION`。
- 生图：填写 `AZURE_OPENAI_ENDPOINT` 和 `AZURE_OPENAI_API_KEY`。

当前生图脚本期望 Azure 资源中存在名为 `gpt-image-2` 的部署。若你的部署名称不同，需要先调整本地适配配置或实现自己的 provider adapter。

根目录 `.env` 会被本地命令读取并被 Git 忽略。项目目录下也可以放 `.env` 来补充缺少的变量，但建议把常用凭据统一放在根目录。

### 3. 准备项目目录

每个案例放在 `output/<project>/`。最重要的人工源文件是：

```text
output/<project>/
├── title.txt
├── narration.txt
├── storyboard_plan.json
├── image_prompts.json
└── images/
```

项目也可以把生图声明拆成 `background_prompts.json` 和 `portrait_prompts.json`。完整结构和字段要求见 `docs/architecture/project-contract.md`。

## TTS 使用说明

默认生成单一女声、广播风格的完整旁白：

```bash
scripts/case-video tts output/<project> \
  --gender female \
  --single-voice \
  --force
```

命令会先规范数字和缩写读法，再生成：

- `audio/narration_azure.wav`：旁白音频。
- `narration.tts.txt`：实际送入 TTS 的文本。
- `narration.tts.plan.txt`：分段合成计划。
- `narration.timeline.json`：后续分镜和字幕唯一使用的时间基线。

使用时注意：

- 人工修改 `narration.txt`，不要直接把 `narration.tts.txt` 当作源文件。
- `CEO`、`CRM`、`ERP` 等缩写保持连续，不要写成带空格的字母。
- 屏幕字幕可以保留阿拉伯数字；TTS 文本由规范器转换成适合朗读的中文。
- 空行用于控制段落停顿。旁白变化后必须重新生成 TTS 和时间轴。
- 只想重生成部分句段缓存时可增加 `--only 3` 或 `--only 3,5-7`；正式全量生成时使用 `--force`。

## 生图使用说明

生图是付费、可能限流的步骤。先确保 schema-v2 分镜计划、Visual Beats 和图片提示词已完成：

```bash
scripts/case-video build output/<project>
scripts/case-video evaluate output/<project>
scripts/case-video ready output/<project> --stage plan
```

先生成一张做连通性和风格测试：

```bash
scripts/case-video images output/<project> --limit 1
```

确认账号、部署、尺寸和风格正常后，再全量生成：

```bash
scripts/case-video images output/<project>
```

`images` 命令会自动再次执行 plan-readiness 检查。默认图片写入项目自己的 `images/`，不要把其他项目的旧图当作新项目的默认素材。

提示词和资产需要遵守这些基本规则：

- 背景图只承载场景和气氛，不放可读文字、数字、Logo、水印、UI 截图或源文档截图。
- 主角不要直接画进背景。人物使用独立的中国人物半身肖像，纯白背景，并保持项目统一风格。
- 最终背景应为 AI 生成或人工策划的叙事插画，不使用占位图、程序化流程图或仪表盘替代。
- 对受限材料只发送抽象后的视觉提示词，不向外部服务上传原始机密文档或长段原文。
- 如遇限流，可设置 `IMAGE_GENERATION_CONCURRENCY=1` 或 `2` 后重试；不要通过重复并发调用制造额外费用。

## 使用字节/火山引擎或其他国内服务

可以使用，但当前仓库没有可直接切换的字节/火山引擎一键适配器。使用者需要自行：

1. 注册并完成服务商要求的实名认证或企业认证。
2. 开通对应的语音合成、图片生成 API、计费和调用额度。
3. 确认可用地域、模型权限、内容审核、数据保存和跨境传输要求。
4. 保管密钥、设置费用告警和最小权限；不要把密钥写进脚本、提示词或仓库。
5. 编写适配器，或手动把结果整理成仓库要求的产物契约。

替换 TTS 服务时，仅有音频文件还不够。适配器必须同时产出可用 WAV 和与 `narration.txt` unit 对齐的 `narration.timeline.json`；若沿用默认渲染配置，最省事的兼容路径是输出到 `audio/narration_azure.wav`，否则需要同步更新项目中的音频引用。

替换生图服务时，输出文件应放在项目 `images/` 下，文件名必须与提示词声明和分镜引用一致。背景、人物肖像、尺寸、白底和风格约束仍然适用。

## 完成渲染与检查

TTS 和图片准备好后，使用统一命令继续：

```bash
scripts/case-video check output/<project>
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
scripts/case-video qa output/<project>
```

查看所有命令和参数：

```bash
scripts/case-video
```

## Git 与生成物

应该版本化人工源文件，例如 `title.txt`、`narration.txt`、`storyboard_plan.json` 和图片提示词声明。项目若已把时间轴或确定性 render IR 纳入版本管理，应继续遵守该项目现有契约。

音频、图片、视频、QA 帧、Remotion 临时输出、PDF 导出、根目录 `tmp/` 和 ffmpeg 两遍压缩日志等可重建产物默认被忽略。不要用 `git add -f` 强行提交这些大文件，也不要提交 `.env`。

检查忽略情况：

```bash
git status --short --ignored
```

## 深入阅读

- 项目知识库：`docs/README.md`
- 新视频工作流：`workflows/new-case-video.md`
- 视频修订工作流：`workflows/revise-video.md`
- TTS 与时间轴：`docs/knowledge-base/tts-and-timing.md`
- 分镜与视觉：`docs/knowledge-base/storyboard-and-visuals.md`
- Agent Skill：`.agents/skills/produce-case-video/SKILL.md`
- 共享引擎：`engine/README.md`
- 可部署服务器：`server/README.md`
