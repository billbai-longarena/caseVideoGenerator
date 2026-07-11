# 共享引擎边界

当前可复用 TTS、素材同步和 Remotion 实现仍位于：

```text
output/budweiser_apac_story_video/
```

这是历史形成的实现位置，不是新项目应直接依赖的公共接口。统一使用：

```bash
scripts/case-video <command> output/<project>
```

`scripts/case-video` 默认指向历史引擎，也支持通过 `CASE_VIDEO_ENGINE_ROOT` 切换到未来独立引擎。迁移共享代码时应保持根命令和项目数据契约稳定。
