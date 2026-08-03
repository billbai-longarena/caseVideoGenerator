# Case Video Generator

把案例材料稳定地生产成可交付的中文案例故事视频。

Case Video Generator 是一个本地优先（local-first）的生产工具链：它把标题、旁白、TTS 时间轴、schema-v2 分镜、AI 视觉资产、Remotion 动效和 ffmpeg/ffprobe 质量检查串成一条可复现流水线。项目同时提供可复用的 Agent Skills，适合销售案例、FDE 变革案例、品牌故事、竖屏短视频和小红书案例视频。

## 先看成片

仓库内已经验证过的竖屏示例是“女性领导力 100”系列 WL-003：

**她从不说“不”，直到当众放错数据**

- 本地文件：`publish/女性领导力/WL-003_她从不说“不”，直到当众放错数据.mp4`
- 画布：1080 × 1920，30 fps
- 编码：H.264 + AAC
- 时长：142.293 秒
- 文件大小：约 47 MB
- 结构：8 个编辑场景、28 个 Visual Beats、2 位具名人物
- 旁白：Azure Speech，`zh-CN-Xiaochen:DragonHDLatestNeural`，dragon-broadcast
- 视觉：`women-leadership-five-color-watercolor`

[打开本地示例视频](<publish/女性领导力/WL-003_她从不说“不”，直到当众放错数据.mp4>)

这条视频展示了项目的完整路径：赵梦琪在客户会议中把 A 项目数据放进 B 项目 PPT，Patrick Liu 在事故后追问她最后一次拒绝请求的时间，随后由具体的资源排期行为完成转折。它不是一个只展示渲染器的空壳样片，而是一个包含人物、事件、旁白、分镜、视觉资产和交付 QA 的完整案例项目。

`publish/` 是本地交付目录，默认被 Git 忽略。因此，在线仓库中的 README 链接只有在本地生成或单独下载该交付文件后可用。建议把大视频放在 Release、对象存储或团队文件库，不要把所有渲染产物塞进 Git 历史。

## 能做什么

- 从案例材料或已批准旁白生成完整故事视频。
- 用 Azure Speech 生成规范化中文旁白和唯一时间基线 `narration.timeline.json`。
- 用 schema-v2 `storyboard_plan.json` 表达场景、Visual Beats、图层、布局、镜头、字幕和资产语义。
- 用 Azure OpenAI `gpt-image-2` 生成背景和人物肖像，并执行尺寸、白底、人物和提示词合同检查。
- 用共享 Remotion 引擎渲染横屏 16:9 或竖屏 9:16 视频。
- 在渲染前执行 plan/render readiness，在渲染后执行 ffprobe、黑帧、时长、字幕和关键帧 QA。
- 将通过 QA 的成片压缩为上传副本，并按 `publish/<主题>/S001_标题.mp4` 组织发布文件。
- 通过本地 Skills 复用生产规则，而不是让每个案例重新发明一套脚本。

## 流水线

```text
案例材料 / 已批准旁白
        ↓
title.txt + narration.txt
        ↓
数字与缩写归一化 → Azure Speech TTS → narration.timeline.json
        ↓
schema-v2 storyboard_plan.json
        ↓
deterministic rich_storyboard.json
        ↓
Azure image2 视觉资产 + 资产 QA
        ↓
Remotion 动效渲染
        ↓
ffprobe / ffmpeg / 关键帧与黑帧 QA
        ↓
video/case_video.mp4 + publish/<主题>/S001_标题.mp4
```

## 5 分钟启动

### 1. 安装本地依赖

需要：

- Python 3
- Node.js 和 npm
- ffmpeg 与 ffprobe
- 可访问 Azure Speech 和 Azure OpenAI image2 的账号

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

cd engine/remotion
npm install
cd ../..
```

可部署服务器是可选组件，只有运行 `server/` 时才需要：

```bash
.venv/bin/python -m pip install -r requirements-server.txt
```

### 2. 配置服务凭据

不要把真实密钥提交到 Git：

```bash
cp .env.example .env
```

最小配置是：

```dotenv
# Azure Speech
AZURE_SPEECH_KEY=...
AZURE_SPEECH_REGION=eastus

# Azure OpenAI image2
AZURE_OPENAI_ENDPOINT=https://<your-resource-name>.openai.azure.com/
AZURE_OPENAI_API_KEY=...
```

生图脚本当前固定调用 `gpt-image-2` 部署，接口版本和部署常量位于 `engine/scripts/generate_images.py`。Azure 资源、部署名称、地区、额度和计费由使用者自行负责。

### 3. 检查一个已有项目

```bash
scripts/case-video check output/women_leadership_03_video
scripts/case-video typecheck output/women_leadership_03_video
scripts/case-video qa output/women_leadership_03_video
```

### 4. 从一个新项目开始

一个标准项目至少需要人工维护：

```text
output/<project>/
├── title.txt                 # 一行标题，也是封面标题来源
├── narration.txt             # 人类可读的旁白源稿
├── storyboard_plan.json      # schema-v2 视觉导演源稿
├── image_prompts.json        # 视觉资产声明
└── images/                   # 本地生成或明确 checkout 的资产
```

完整的项目合同见 [`docs/knowledge-base/production-principles.md`](docs/knowledge-base/production-principles.md)、[`docs/knowledge-base/storyboard-and-visuals.md`](docs/knowledge-base/storyboard-and-visuals.md) 和 [`docs/architecture/visual-beat-system.md`](docs/architecture/visual-beat-system.md)。

## 常用命令

所有生产命令都从仓库根目录执行：

```bash
# 内容、分镜和准备度
scripts/case-video build output/<project>
scripts/case-video evaluate output/<project>
scripts/case-video ready output/<project> --stage plan

# TTS：生成音频和唯一时间基线
scripts/case-video tts output/<project> \
  --gender female \
  --single-voice \
  --force

# 生图：先限量测试，再全量生成
scripts/case-video images output/<project> --limit 1
scripts/case-video images output/<project>

# 渲染前后检查
scripts/case-video ready output/<project> --stage render
scripts/case-video render output/<project>
scripts/case-video qa output/<project>

# 预览、关键帧和发布
scripts/case-video preview output/<project>
scripts/case-video intent-frames output/<project>
scripts/case-video publish output/<project>
```

完整命令列表：

```bash
scripts/case-video
```

## Source of truth

项目故意把“创意决策”和“渲染机械”分开：

- `title.txt` 和 `narration.txt` 是人类创作源稿。
- `narration.timeline.json` 是所有分镜和字幕的时间基线。
- `storyboard_plan.json` 是视觉方向、场景、Visual Beats、图层、资产、镜头和字幕的源稿。
- `rich_storyboard.json` 是确定性编译得到的 render IR；v2 项目不要手改它来替代 plan。
- `image_prompts.json` 和 `asset_pool_usage.json` 记录视觉资产的生成与来源。
- Remotion 负责可重复的像素布局、插值、合成和输出，不负责替模型补写创意。

这个边界是项目可复现性的核心：改旁白先重新生成 TTS 和 timeline；改视觉先更新 plan，再重新 build、ready、生成资产和 render。

## 目录速览

```text
.
├── .agents/skills/             # 可复用生产 Skills
├── engine/                     # TTS、生图、Remotion 共享引擎
├── scripts/case-video          # 统一 CLI 入口
├── workflows/                  # 新建、修订、竖屏和资产复用工作流
├── docs/                       # 长期生产知识库与架构合同
├── output/<project>/           # 案例源稿、计划、时间轴和项目元数据
├── assets/                     # 经过 QA 的共享视觉资产索引
├── input/                      # 原始材料和系列选题
├── server/                     # 可选的异步服务端实现
└── publish/                    # 本地上传副本，默认 Git-ignored
```

## 质量门

不要只看“文件渲染出来了没有”。交付前至少检查：

- 视频和音频流存在，编码、分辨率、帧率和时长正确。
- 旁白时长与视频接近，`narration.timeline.json` 没有漂移。
- 没有黑帧、空白画布或被不透明蒙层遮住的背景。
- 标题、字幕、关键词、人物肖像和信息卡不互相覆盖。
- 竖屏项目使用 1080 × 1920 和移动安全区，不把横图硬裁成竖图。
- 生图提示词和人物肖像满足中文人物、纯白背景、半身构图等项目合同。
- 公开仓库不包含 API Key、`.env`、客户原文或未经授权的品牌资产。

## Agent Skills

仓库内的 Skill 适用于 Codex 或其他遵循同类目录协议的代理：

- [`produce-case-video`](.agents/skills/produce-case-video/SKILL.md)：销售与销售管理案例。
- [`produce-fde-video`](.agents/skills/produce-fde-video/SKILL.md)：FDE / AI 组织转型案例。
- [`produce-brand-story-video`](.agents/skills/produce-brand-story-video/SKILL.md)：品牌故事视频。
- [`produce-salesnail-video`](.agents/skills/produce-salesnail-video/SKILL.md)：SalesNail 产品案例。
- [`produce-vertical-video`](.agents/skills/produce-vertical-video/SKILL.md)：通用 9:16 竖屏视频。
- [`produce-xiaohongshu-video`](.agents/skills/produce-xiaohongshu-video/SKILL.md)：小红书 2–3 分钟案例视频。
- [`produce-english-case-video`](.agents/skills/produce-english-case-video/SKILL.md)：英文案例视频。

代理开始生产前，先读取对应 Skill、知识库和工作流。不要把旧的 `output/` 成片当成新项目的创意模板；历史输出只用于用户明确要求的审计或修订。

## 深入阅读

- [`docs/README.md`](docs/README.md)：知识库与工作流索引。
- [`workflows/new-case-video.md`](workflows/new-case-video.md)：横屏案例视频完整流程。
- [`workflows/new-vertical-video.md`](workflows/new-vertical-video.md)：9:16 竖屏流程。
- [`workflows/new-xiaohongshu-case-video.md`](workflows/new-xiaohongshu-case-video.md)：小红书短版流程。
- [`engine/README.md`](engine/README.md)：共享引擎边界。
- [`server/README.md`](server/README.md)：可选异步服务端。
- [`AGENTS.md`](AGENTS.md)：本仓库的生产约束和协作协议。

## 开源与素材边界

代码和生产工具以 [`MIT License`](LICENSE) 发布。MIT 许可证只覆盖项目代码及其原创脚本，不自动授予以下内容的额外权利：

- 客户提供的 DOCX、PPTX、PDF、原始案例材料和内部数据。
- SalesNail、WorkBuddy 或其他品牌 Logo、字体和第三方素材。
- 具体案例旁白、成片、上传副本和客户定制内容。
- Azure、Remotion、ffmpeg 及其他第三方依赖本身的许可证和服务条款。

在把 GitHub 仓库设为 Public 之前，请先完成一次公开发布清单：

1. 移除或替换 `input/customization/`、客户原文、账单/支持沟通记录和不具备公开授权的品牌素材。
2. 清理 Git 历史中的同类文件；仅从当前工作树删除并不能从历史提交中移除它们。
3. 保留 `.env`、`.envskill`、密钥、数据库配置、登录凭据和本地运行状态在仓库之外。
4. 将大视频放到 Release 或对象存储，并确认示例案例和人物/品牌素材具有公开授权。

这是一个生产工具仓库，不是云服务。使用者需要自行承担云服务账号、计费、配额、数据区域、隐私、版权和内容合规责任。

## 许可证

除第三方内容和明确注明其他许可证的文件外，项目代码按 [`MIT License`](LICENSE) 发布。
