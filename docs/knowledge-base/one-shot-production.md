# 一次成型生产门禁与复盘

## 目标

一次成型指：内容合同、分镜合同、素材完整性和真实像素检查在长渲染前全部通过；整片第一次启动后无需修改源计划、素材声明或 Remotion 代码即可完成渲染、QA 和发布。provider 重试不计作内容返工，但必须记录。

## 本轮暴露的返工原因

| 类别 | 具体表现 | 固化的防线 |
| --- | --- | --- |
| 内容合同 | FDE 固定开收场、禁用对比句、业务缩写连写和案例边界没有在最早阶段锁定，后续 TTS 前仍需改旁白。 | `preflight --stage content`、`case_inputs.json`、FDE skill 的固定文案门禁 |
| schema / 校验器 | 计划使用了未被当前 validator 接受的转场，部分 beat 只有镜头变化却没有语义变化，删除重复 beat 后又产生过长语义空窗。 | `preflight --stage plan`、严格 `check`、语义签名检查、12 秒语义空窗门禁 |
| 视觉构图 | 对白或计数卡保留了通用标题层；人物、对白框、计数卡之间发生重叠；背景被误声明为人物。 | 预检的 semantic-layer-overlap、`bg-*`/`portrait-*` 角色检查、真实 intent-frame 审核 |
| 素材与 provider | Azure 生图出现 RemoteDisconnected 重试；EP14 曾把 864×1536 背景声明为人物，只有在编译资产尺寸检查时才暴露。 | 项目内素材完整性检查、角色/尺寸检查、先意图帧后长渲染 |
| 渲染 workspace | EP10 首次整片渲染中途出现图片 404，根因是多个 Remotion 进程共享同步目录。 | 每次 Remotion 调用使用隔离 workspace；渲染前必须通过 render preflight |

## 强制顺序

`content preflight → TTS → build/evaluate/ready(plan) → plan preflight → 生图 → check/typecheck → intent-frames + 人工审核 → ready(render) → render preflight → render → ffprobe/blackdetect/contact sheet → publish`

每次返工都必须归入上表五类之一，并把同类缺陷转成脚本门禁、skill 条款或知识库规则。不得通过手改 `rich_storyboard.json`、JSX 或 MP4 绕过源合同。

## 一次成型率记录

每个项目在第一次完整 render 前记录 `renderAttempt=1`；若因源合同、计划、素材声明或渲染环境失败而再次启动，递增 attempt 并保留失败日志。最终统计同时报告：

- 首次完整 render 通过数 / 项目数；
- preflight 拦截的修正数；
- provider 重试数；
- 渲染后像素 QA 发现的返工数。

只有最后一项属于“长渲染后返工”。目标是把问题尽量前移到 content、plan 和 render 三道廉价门禁。

## EP11–EP16 验证结果

本轮六个项目在最终 render preflight 通过后，第一次完整渲染全部成功，首轮完整 render 通过率为 **6/6（100%）**，长渲染后返工为 0。六个项目在进入最终门禁前都发生过计划或内容修正，因此这个数字衡量的是“通过门禁后的首轮完整渲染稳定性”，不是未经检查的初稿零修改率。

详细的时长、master 大小、readiness 分数、失败类别和发布文件记录在 `output/fde_ep10_smartmfg_90day/qa/one-shot-rate.json`。
