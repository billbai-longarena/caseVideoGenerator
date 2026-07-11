# Case Video Playbook

本文件保留为向后兼容入口。项目的长期知识和可执行流程已经拆分：

```text
docs/README.md                          # 知识地图
docs/knowledge-base/production-principles.md
workflows/new-case-video.md             # 新案例完整生产
workflows/revise-video.md               # 局部修订
.agents/skills/produce-case-video/      # Agent 执行规范
```

## 不可破坏的默认规则

- 用户未指定时长时，生成 4–7 分钟案例视频。
- `narration.timeline.json` 是唯一时间基准。
- `rich_storyboard.json` 是唯一分镜数据源。
- 使用 narration unit 编号，不用手写秒数代替语义时间。
- 销售案例默认栏目为 `销售不复杂`，使用固定片头、片尾和字幕栏标签。
- 默认使用 Azure Speech Dragon HD 男女声按段落交替的 `dragon-broadcast` profile。
- 中文旁白和字幕避免 `不是……而是……` 及近似表达。
- Remotion 负责 motion graphics，ffmpeg/ffprobe 负责换轨、编码和 QA。
- 通用规则更新到 `docs/`，案例专属记录留在 `output/<project>/`。

## 推荐命令

```bash
scripts/case-video check output/<project>
scripts/case-video tts output/<project>
scripts/case-video render output/<project>
scripts/case-video qa output/<project>
```

百威目录下的 `VIDEO_PRODUCTION_WORKFLOW.md` 现在是历史案例实现记录，不再作为项目总入口。
