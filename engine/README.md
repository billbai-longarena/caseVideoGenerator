# 共享引擎

可复用的 TTS、素材同步、生图和 Remotion 渲染实现位于本目录：

```text
engine/
  remotion/            # 共享 Remotion 工程（视觉引擎）
  tts_compare/         # TTS 生成与时间轴
  scripts/             # sync_assets.sh、mux_audio.sh、make_sfx.sh、generate_images.py 等
  tts_text_normalizer.py
```

引擎不持有任何案例数据。案例项目位于 `output/<project>/`，通过根命令访问引擎：

```bash
scripts/case-video <command> output/<project>
```

`scripts/case-video` 默认指向本目录，也支持通过 `CASE_VIDEO_ENGINE_ROOT` 切换到实验引擎。修改引擎时保持根命令和项目数据契约稳定；单案例的特殊需求写入案例目录，不进入引擎。
