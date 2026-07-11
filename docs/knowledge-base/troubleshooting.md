# 常见故障

## TTS 数字读错

先检查 `narration.tts.txt`，再修 normalizer 并重新生成音频。不要只改屏幕字幕。

## 女声单人或语速不一致

检查 `--gender female --single-voice`、profile、voice、rate 和 pitch。确认片头片尾没有使用旧设置单独拼接；除非用户明确要求，不要恢复男女声交替。

## 分镜与音频错位

确认 timeline 是由当前音频生成，scene unit 连续覆盖全部 timeline units。删除手写秒数，改用 `atUnit`。

## Remotion 找不到素材

运行项目 `check`，确认 storyboard 音频路径和图片路径存在，再运行同步或渲染命令。不要在 `staticFile` 路径中加入 `public` 前缀。

## 首次渲染慢或原生依赖错误

确认 Node 架构为 `arm64`，重新安装依赖，并保留 Chromium 缓存。

## ffmpeg 单帧警告

单帧 PNG 可正常写出；需要消除 filename pattern warning 时添加 `-update 1`。

## 并行项目素材串线

当前共享 Remotion 工程使用同一个 generated/public 目录。不要并行渲染多个项目；按项目串行执行同步和渲染。
