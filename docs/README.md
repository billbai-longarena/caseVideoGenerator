# 项目知识库

这里是案例视频项目的长期知识入口。可复用规则放在 `docs/`，操作步骤放在 `workflows/`，Agent 执行规范放在 `.agents/skills/produce-case-video/`，具体案例数据放在 `output/<project>/`。

## 新任务阅读顺序

1. `architecture/repository-layout.md`：先理解目录职责和变更边界。
2. `knowledge-base/production-principles.md`：确认全局默认值和 source of truth。
3. 按任务读取对应专题文档。
4. 执行 `../workflows/` 中匹配的工作流。

## 专题索引

- `knowledge-base/production-principles.md`：生产原则、时长、栏目和数据源。
- `knowledge-base/case-story-model.md`：销售案例的三类竞争、客户真相线、信息披露线、销售认知线和参数化生成模型。
- `knowledge-base/narration.md`：标题与旁白同期创作、案例改写、中文口播、栏目文案和时长预算。
- `knowledge-base/tts-and-timing.md`：Azure Speech、数字归一化、音色和时间轴。
- `knowledge-base/storyboard-and-visuals.md`：分镜 JSON、unit 锚点、布局和生图。
- `knowledge-base/visual-asset-pool.md`：共享背景素材池、场景词表、多轴标签、归档和可选复用原则。
- `knowledge-base/rendering.md`：Remotion、素材同步、渲染和快速换轨。
- `knowledge-base/qa-and-delivery.md`：技术质检、视觉质检和交付门槛。
- `knowledge-base/vertical-mobile-video.md`：竖屏 9:16 手机视频的画布合同、移动最佳实践和与横屏流水线的差异。
- `knowledge-base/salesnail-workbuddy-collab.md`：SalesNail × WorkBuddy 联名视频的右上常驻双 Logo 标识合同、Logo 资产来源和 plan `coBrand` 声明。
- `knowledge-base/publishing.md`：内部成片与集中发布目录、`S001_标题.mp4` 命名、批量上传清单和 Git 边界。
- `knowledge-base/tooling-decisions.md`：工具选型及历史决策。
- `knowledge-base/troubleshooting.md`：常见故障与处理顺序。
- `architecture/server-deployment-design.md`：异步任务服务器、严格模型路由、Phase A 现状，以及 Phase B/C 的数据、审核、UI、扩容、运维与验收合同。
- `acceptance/server-b-c-status.md`：Phase B/C 验收 ID 的实时状态、证据和未完成项；`partial` 不视为放行。
- `architecture/visual-beat-system.md`：Visual Beat 分层编辑的数据合同、兼容策略、校验边界和验收标准。
- `architecture/llm-director-pipeline.md`：LLM 导演源稿、确定性编译器、Remotion 执行层和 intent-to-frame 复核之间的责任边界。
- `kimi-code-azure-k3.md`：Kimi Code 连接 Azure Foundry K3、默认 YOLO，以及 Low/High/Max Thinking 配置与排障。

## 工作流索引

- `../workflows/generate-case-story.md`：从材料或参数生成销售案例模型和故事正文。
- `../workflows/new-case-video.md`：从材料到成片。
- `../workflows/new-vertical-video.md`：竖屏 9:16 手机视频(从标题旁白到竖版成片)。
- `../workflows/revise-video.md`：旁白、画面和局部修订。
- `../workflows/reuse-visual-assets.md`：新图 QA 后入池归档，以及在明确需要复用或修订连续性时检索、复核和 checkout。
- `../workflows/improve-production-system.md`：按证据把复盘结论沉淀到正确层，并完成兼容回归。
- `../workflows/README.md`：工作流使用规则与质量门。

## 历史资料

`output/budweiser_apac_story_video/VIDEO_PRODUCTION_WORKFLOW.md` 保留为第一条完整流水线的案例实现记录。它不再承担项目总入口职责。新的通用规则应更新到本知识库，百威专属细节继续留在该案例目录。

根目录的 `案例写作方法论.md`、`案例转旁白脚本方法论.md` 和 `AZURE_SPEECH_TTS_GUIDE.md` 是历史长文参考。它们暂时保留原路径以避免破坏外部引用；当前生产规范以本知识库和工作流为准。
