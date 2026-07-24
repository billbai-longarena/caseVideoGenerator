# 共享视觉素材归档与可选复用工作流

适用于新生成素材通过 QA 后入池归档、用户明确要求复用、修订需要视觉连续性，或分镜有意 callback、对照、证据放大的场景。新视频默认先生成新素材，不以共享池检索作为起点。分类原理和场景词表见 `../docs/knowledge-base/visual-asset-pool.md`。

## 1. 刷新素材池（归档或明确复用前）

输入：现有 `output/<project>/` 案例文本、分镜、提示词和 `images/`。

```bash
scripts/visual-assets build
scripts/visual-assets audit
```

质量门：audit 通过；`catalog.json` 中没有丢失二进制、哈希错误或无主分类资产。

## 2. 建立归档或复用简报

对每个待选 Visual Beat 至少记录：

- 空间：在哪里。
- 行为：人物正在做什么。
- 参与者和关系：谁面对谁，谁拥有权力或信息。
- 叙事职责：建立、识别、证据、解释、升级、后果、回响或重置。
- 目标视觉家族、镜头角度、情绪和文字留白。

不要直接把整段旁白当成唯一查询。先拆出稳定的视觉意图。

质量门：每个需求都能用两个以上标签描述，且没有把“会议”“公司”等宽泛词当成完整画面。

## 3. 可选检索候选

默认新案例和新背景资产跳过本步骤，直接进入第 6 步生成新素材。只有明确复用、修订连续性或有意 callback、对照、证据放大时，才检索候选：

```bash
scripts/visual-assets search 工厂 产线 --setting 产线 --activity 生产 --limit 8
scripts/visual-assets search 会议 决策 --setting 会议室 --activity 审批 --style 管理者剪影 --limit 8
scripts/visual-assets search 门店 货架 --setting 门店 --activity 渠道走访 --style 销售水彩 --limit 8
```

可组合 `--setting`、`--activity`、`--participant`、`--story-function`、`--object`、`--mood`、`--industry` 和 `--style`。参数接受受控 ID、中文标签或别名。

质量门：候选来自目标画风，并在空间、行为和叙事职责上至少满足主要需求。

## 4. 人工视觉复核

打开候选原图或 `assets/visual-pool/views/`，检查：

- 主体和人物关系是否准确。
- 构图是否支持字幕、标题和信息卡。
- 图片是否含可读文字、数字、logo、水印或异常肢体。
- 情绪、行业线索和镜头距离是否服务当前旁白。
- 与前后画面的空间、角色和镜头是否有足够变化。

标签召回只负责缩小范围，不能替代看图。

同时检查四类适配性：叙事语义、人物身份与关系、视觉家族、构图与安全区。这里采用定性门槛，不用固定分数替代判断。任一关键项需要靠字幕才能“解释正确”，或人物年龄、朝向、风格与角色明显不符，都应判定为素材缺口。

若原图与自动标签不一致，把稳定素材 ID 写入 `assets/visual-pool/tag_overrides.json`，按维度使用 `replace`、`add` 或 `remove` 并附 `note`，然后重新运行 `build` 和 `audit`。单张图的特殊语义不要写进全局 taxonomy 关键词。

质量门：选中素材无需靠字幕纠正其核心语义。

## 5. Checkout 到项目（仅限刻意复用）

```bash
scripts/visual-assets checkout <asset-id> output/<project>
```

默认复制到 `output/<project>/images/pool/`，并更新 `asset_pool_usage.json`。如需稳定的项目内名称可使用 `--name scene-05-factory.png`。

把命令输出的资产片段加入 storyboard `visualAssets`，或将本地路径用于背景 cue。必须保留 `origin: "curated"` 和 `poolAssetId`；不要直接引用共享池路径。

质量门：本地图片存在，`asset_pool_usage.json` 的 SHA-256 与文件一致，`scripts/case-video check output/<project>` 通过。

## 6. 生成新素材

新视频默认走本步骤：按 Visual Beat 直接生成新图。明确复用任务中，没有候选，或候选在语义、画风、人物身份与关系、构图、留白上不合格时，也走本步骤：

1. 为当前视觉需求编写可复现提示词；修订时不重生已经明确合格且需要保留的素材。
2. 背景图写入项目 `image_prompts.json`；缺少合适 NPC 时扩展人物池规格，并限定需要补充的画风和人物属性。
3. 按项目视觉家族生成新图。
4. 完成文字、logo、构图、人物和叙事语义 QA。
5. 在 storyboard 中将项目新图标记为 `origin: "generated"`；从人物池生成并 checkout 的头像仍按池中资产记录为 `origin: "curated"`。

不能为了避免生图而使用语义不符的池中图片，也不能用程序图或占位图替代最终背景。

质量门：池中素材由 `asset_pool_usage.json` 覆盖；新生成素材由 `image_prompts.json` 覆盖；所有 storyboard 引用都能解析。

## 7. 检查单条视频内的重复

跨项目复用本身应有明确理由并保留 provenance。若同一条视频的多个主场景重复使用同一项目本地图片，必须确认它是 callback、对照、证据放大或明确兜底，并在 scene 或 cue 标记 `reuse` / `allowBackgroundReuse`。

质量门：没有因为素材不足而机械重复最后一张图。

## 8. 回流和验收

完成渲染与视觉 QA 后，背景叙事图运行：

```bash
scripts/visual-assets build
scripts/visual-assets audit
scripts/case-video check output/<project>
```

新生成且合格的背景图会在下一次 build 中去重、打标并进入共享池。查看 `assets/visual-pool/coverage_report.md`，确认新增素材确实缩小了目标缺口，没有制造异常标签。

背景 build 会忽略项目的 `images/characters/`。人物头像必须走下面的独立人物池流程，不能让头像按所在分镜自动继承仓库、会议室或谈判等背景标签。

缺少合适人物时，向 `assets/character-portraits/specs.json` 增加人物 profile；可用可选 `styles` 只补指定视觉家族。随后执行：

```bash
scripts/character-portraits prepare
python3 engine/scripts/generate_images.py \
  --project assets/character-portraits \
  --prompts assets/character-portraits/generation_prompts.json \
  --concurrency 2 --quality medium
scripts/character-portraits finalize --reviewed
scripts/character-portraits audit
```

先看新头像和 contact sheet，再标记 reviewed。生成完成后重新 search/checkout；不要把仅适用于某个姓名或公司的文字写进共享头像。

最终质量门：

- 项目只引用本地素材。
- 刻意复用素材有可验证来源和哈希。
- 新生成素材有可复现提示词。
- 新生成且可复用的背景或人物已经进入对应素材池，并能被下一项目检索。
- 同一视频内的重复有明确叙事意图。
- 画风、语义、构图和安全区通过人工检查。
