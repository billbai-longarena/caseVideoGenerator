# 工作流使用说明

工作流只描述执行顺序、输入输出和质量门。背景知识由 `../docs/knowledge-base/` 维护，命令由 `../scripts/case-video` 统一提供。

## 选择工作流

- 从材料或参数新写、重构销售案例：`generate-case-story.md`
- 新案例或完整重做：`new-case-video.md`
- 改旁白、音色、字幕、分镜、图片或局部成片：`revise-video.md`
- 检索共享图片、把素材取入项目或补齐场景图片：`reuse-visual-assets.md`
- 把生产复盘沉淀到 Skill、工作流、知识库、校验器或共享引擎：`improve-production-system.md`

## 阶段规则

- 每个阶段结束先过质量门，再进入下一阶段。
- 生成物失败时回到它的直接来源修复，不在下游补丁中掩盖问题。
- 跨案例规则变化更新 `docs/`；单案例决策留在 `output/<project>/`。
