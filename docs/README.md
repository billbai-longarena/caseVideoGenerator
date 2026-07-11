# 项目知识库

这里是案例视频项目的长期知识入口。可复用规则放在 `docs/`，操作步骤放在 `workflows/`，Agent 执行规范放在 `.agents/skills/produce-case-video/`，具体案例数据放在 `output/<project>/`。

## 新任务阅读顺序

1. `architecture/repository-layout.md`：先理解目录职责和变更边界。
2. `knowledge-base/production-principles.md`：确认全局默认值和 source of truth。
3. 按任务读取对应专题文档。
4. 执行 `../workflows/` 中匹配的工作流。

## 专题索引

- `knowledge-base/production-principles.md`：生产原则、时长、栏目和数据源。
- `knowledge-base/narration.md`：案例改写、中文口播、栏目文案和时长预算。
- `knowledge-base/tts-and-timing.md`：Azure Speech、数字归一化、音色和时间轴。
- `knowledge-base/storyboard-and-visuals.md`：分镜 JSON、unit 锚点、布局和生图。
- `knowledge-base/rendering.md`：Remotion、素材同步、渲染和快速换轨。
- `knowledge-base/qa-and-delivery.md`：技术质检、视觉质检和交付门槛。
- `knowledge-base/tooling-decisions.md`：工具选型及历史决策。
- `knowledge-base/troubleshooting.md`：常见故障与处理顺序。

## 工作流索引

- `../workflows/new-case-video.md`：从材料到成片。
- `../workflows/revise-video.md`：旁白、画面和局部修订。
- `../workflows/README.md`：工作流使用规则与质量门。

## 历史资料

`output/budweiser_apac_story_video/VIDEO_PRODUCTION_WORKFLOW.md` 保留为第一条完整流水线的案例实现记录。它不再承担项目总入口职责。新的通用规则应更新到本知识库，百威专属细节继续留在该案例目录。

根目录的 `案例写作方法论.md`、`案例转旁白脚本方法论.md` 和 `AZURE_SPEECH_TTS_GUIDE.md` 是历史长文参考。它们暂时保留原路径以避免破坏外部引用；当前生产规范以本知识库和工作流为准。
