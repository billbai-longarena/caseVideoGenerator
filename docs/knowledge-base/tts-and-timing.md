# TTS 与时间轴

## 默认引擎与音色

- 默认使用 Azure Speech TTS。
- 当前默认只使用女声：`zh-CN-Xiaochen:DragonHDLatestNeural`。
- 男声 `zh-CN-Yunfan:DragonHDLatestNeural` 仅保留为历史兼容或用户明确要求的 A/B 选项，不作为默认交付音色。
- 默认 `dragon-broadcast` 女声 profile：rate `+7%`、pitch `+1%`；段落间隔 `0.45s`。
- `销售不复杂` 固定片头、正文和片尾统一使用 `dragon-broadcast` 配置。
- 交付音频默认使用单一女声：`scripts/case-video tts output/<project> --gender female --single-voice --force`。
- 空行只表达段落停顿和合成切分，不再默认触发男女声交替。

## 归一化

- 年份按逐位读法，例如 `2019 年` 读作 `二零一九年`。
- 金额、百分比、小数、倍数和范围按语义读法转换。
- 源旁白、屏幕字幕和归一化 TTS 文本中的 `IT`、`ERP`、`CRM`、`SKU`、`CIO` 等缩写保持连写，不在字母之间或缩写与相邻中文之间加空格；当前 Azure Dragon HD 音色不再使用 `I T`、`C E O` 这类空格分隔技巧。
- `618 大促` 等标签按逐位数字读作 `六一八大促`。
- 修复归一化规则后重新生成音频，不只修改字幕。

## 时间轴

- `narration.timeline.json` 记录每个 unit 的 `index`、`text`、`start`、`end` 和停顿。
- Remotion 场景边界、字幕切换、关键词、背景和总时长都从 timeline 推导。
- 更换 voice、rate、pitch、SSML 或段落结构后必须重建 timeline。
- 短枚举的 TTS 内部停顿不能改变屏幕和分镜 unit 编号。

## 操作原则

- 完整生成使用 `scripts/case-video tts output/<project>`。
- 局部修复可传 `--only`；整体配置变化使用 `--force`。
- 不用单一全局速度覆盖已验证的女声 broadcast profile，除非新的听感测试明确替换默认 profile。
- 生成后试听片头、段落切分点、数字密集段和片尾。
