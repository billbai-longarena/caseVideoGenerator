# 新案例视频工作流

## 1. 建立项目

输入：案例材料、目标受众、期望时长和交付要求。

- 在 `output/<project>/` 建立独立案例目录。
- 明确材料使用边界，记录不能外发的内容。
- 用户未指定时长时采用 4–7 分钟。

质量门：项目命名明确，材料边界和目标时长已确认。

## 2. 改写旁白

- 提炼故事矛盾和叙事视角。
- 写入 `narration.txt`，用空行控制段落停顿和合成切分；默认不做男女声交替。
- 销售案例加入固定栏目片头、片尾和品牌信息。
- 定稿前由大模型复核自然中文、短句、英文术语、缩写连写、数字读法风险和禁用对比句式。

质量门：脚本长度接近目标时长，故事弧线完整，可自然朗读。

## 3. 生成 TTS 与时间轴

```bash
scripts/case-video tts output/<project> --gender female --single-voice --force
```

- 检查归一化文本、女声单人 profile、数字读法和停顿。
- 必要时修 normalizer、文本标点或段落结构后重跑。

质量门：`narration.timeline.json` 与当前音频一致，重点段试听通过。

## 4. 建立分镜

- 以 timeline unit 编号划分连续场景。
- 在 `rich_storyboard.json` 填写字幕、标题、关键词、布局、背景和语义揭示 unit。
- 运行项目检查：

```bash
scripts/case-video check output/<project>
```

质量门：unit 连续覆盖，音频和图片引用有效，没有手写秒数替代 unit timing。

## 5. 生成视觉资产

- 先确定一个视觉家族，再按场景写 `image_prompts.json`。销售案例默认沿用蓝黄水彩：亮钴蓝/天蓝、镉黄高光、高明暗对比、奶油纸面、透明水彩/水粉叠色、干刷边缘、前景清楚、背景半抽象低细节。销售管理案例默认沿用本地暖色经理剪影风格：近黑人物剪影、深海军蓝层次、钴蓝、焦橙、灰桃色、奶油到琥珀背光、剪纸/丝网印刷感、干净留白。
- 生图只使用抽象重写后的场景描述。
- 销售水彩图提示词不要写红色、珊瑚红、铁锈橙、橙红作为风格色；除非案例事实必须出现极小警示色。经理剪影风格允许本地参考里的焦橙和灰桃色背光，但不得生成红色水彩。
- 禁止在背景图里生成可读文字、数字、字母、logo、水印、UI 截图或来源文档截图；数字、金额、百分比和英文缩写放到 Remotion 文本层。
- 最终背景只能使用 AI 生成或人工挑选的叙事插画。AI 生图失败时修配置或停止，不使用 PIL/Canvas/SVG/程序几何图/图标集/流程图/仪表盘/占位图替代。
- 主流程要求 `image_prompts.json` 中的 prompt 文件、`rich_storyboard.json` 主背景引用和实际图片文件与场景数量对齐。不要因为图片不足让后续 layout 一直播放最后一张图。
- 图片复用只能作为显式兜底，并在 scene 或 background cue 上标记 `allowBackgroundReuse`/`reuse`；不能作为默认生成策略。
- 检查构图变化、文字留白、logo、可读文字、数字伪影和水印。

质量门：所有背景服务具体语义，画风统一且镜头不机械重复，没有程序图或文字数字伪影。

## 6. 预览与渲染

```bash
scripts/case-video typecheck output/<project>
scripts/case-video preview output/<project>
scripts/case-video render output/<project>
```

质量门：预览无布局冲突，typecheck 通过，完整渲染成功。

## 7. 质检与交付

```bash
scripts/case-video qa output/<project>
```

- 抽 contact sheet 和关键帧。
- 完成视觉检查和数字密集段试听。
- 记录最终文件、时长、规格和已知限制。

质量门：满足 `docs/knowledge-base/qa-and-delivery.md` 的全部交付门槛。
