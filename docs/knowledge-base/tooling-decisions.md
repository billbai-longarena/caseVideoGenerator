# 工具选型与决策

## 当前组合

- Azure Speech：默认旁白生成和 word-boundary 时间轴。
- Azure OpenAI 图像生成：抽象背景和编辑插画素材。
- Remotion：JSON 驱动的字幕、花字、布局、转场和 motion graphics。
- ffmpeg/ffprobe：换轨、编码、抽帧、contact sheet 和技术质检。

## 为什么使用 Remotion

案例视频需要模板化的信息层、旁白同步和可复用布局。纯 ffmpeg 适合编码和简单推拉，不适合作为复杂 motion graphics 主层。After Effects 或剪映适合人工精剪，但自动化、版本控制和批量复用较弱。

## 历史兼容

- CosyVoice 保留为 Azure 不可用或用户明确要求离线 TTS 时的 fallback。
- 句级缓存 profile 保留给局部修复和兼容，不作为默认生产模式。
- 历史案例目录曾承载共享引擎；当前共享实现统一位于 `engine/`。

## 决策记录规则

只有跨案例、长期有效且经过验证的选择才写入本文件。单个样音、单个案例构图或临时实验结果留在对应输出目录。
