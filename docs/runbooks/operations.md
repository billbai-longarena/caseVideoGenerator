# Case Video 生产运维 Runbook

Owner：`platform-oncall`（平台依赖）、`application-oncall`（API）、`worker-oncall`（队列/worker）、`model-platform-oncall`（模型路由）。任何处理都要记录开始时间、request/trace ID、影响范围、是否暂停付费阶段、恢复动作和验证结果；日志不得写 source、prompt、模型完整响应、密钥或签名 URL。

## Metrics collection

1. 影响判断：确认 `/health/live`、`/health/ready` 和带最小权限令牌的 `/metrics`；查看 `casevideo_metrics_collection_success` 与采集时间。
2. 停止损失：采集失败伴随数据库或对象存储故障时，暂停新 job 和付费 worker；保留只读 API。
3. 恢复：分别验证数据库 schema/read、对象存储 list/head；修复后重启单个 API 实例，不进行隐式 migration。
4. 验证：连续三次抓取成功，指标时间递增，队列/租约值能与 `/admin/operations` 对上，且指标中无高基数 ID。

## API errors

1. 按路由模板和 trace ID 划定 5xx；核对最近发布、数据库连接、对象存储和 Redis。
2. 若错误影响写入或付费调用，关闭新任务入口并停止 planning/media/render worker 领取新任务；不要删除 outbox。
3. 回滚应用时保留已经扩展的数据库 schema，不回滚数据；或发布前向修复。
4. 以一个只读请求、一个 stub dry-run job 和一个已存在 artifact 下载完成验证。

## Queue stalled

1. 在运维页核对 queue depth、最老年龄、活动/过期租约、outbox 和模型 readiness。
2. 暂停该队列的新付费 stage；已有 provider 调用按调用 ID/费用账本核对，禁止盲目重复执行。
3. 先运行 reaper，再运行 outbox/queue rebuild；仅对输入 snapshot 未变化且没有成功 paid result 的 stage 重投。
4. 确认队列年龄下降、stage event 在两秒内可见、没有新增重复费用或 superseded 结果被提升。

## Dead letter

1. 获取运维页给出的 stage、attempt、稳定错误码和诊断 ID，不在群聊粘贴材料内容。
2. 判断是永久输入错误、provider/容量故障还是版本兼容问题；永久错误回到用户修订，临时故障才允许恢复。
3. 恢复操作创建新 stage run，旧 dead-letter 行保留；付费阶段先展示预计新增费用并取得相应权限确认。
4. 验证 job、队列、审计和费用账本指向同一个新 attempt。

## Expired lease

1. 确认 worker 进程、节点资源和临时工作区是否仍存在；不要在租约未过期时抢占。
2. render 进程残留时先 TERM，等待配置的 grace period 后 KILL，并清理该 job 独立 scratch。
3. 运行 reaper；已有成功结果时走幂等复用，没有成功结果才生成新 attempt。
4. 验证租约释放、临时目录清空、对象无错误提升、费用无重复。

## Outbox

1. PostgreSQL/outbox 是恢复依据，Redis 不是权威事实。先备份或快照数据库。
2. 检查 Redis 连通、consumer group、dispatcher 日志和失败原因；禁止直接标记未发送事件为 delivered。
3. 执行 outbox rebuild 和 dispatch；重复投递由 stage 幂等键吸收。
4. 对比 queued stage、undelivered outbox、Redis stream 数量并抽查 job event sequence。

## Model route

1. 只检查配置项是否存在、endpoint 可达和 provider 返回的请求 ID；不得打印 key。
2. `narration` 与 `remotion` 必须为 `azure_anthropic`，部署名/请求体 `model` 都使用 `salesnail-cs-46`，endpoint 必须是 Azure Anthropic Messages（通常为 `/anthropic/v1/messages`），transport 记录为 `anthropic_messages`。不得把该路由发往 Azure OpenAI，也不得把 request model 改成底层 `claude-*` 型号 ID。`general` 必须为 `gpt-5.5` Responses API。
3. 任一路由不可用就暂停相应 stage；禁止切到另一模型或历史 fallback。
4. 用不含敏感材料的最小请求验证，再检查 model run 的 provider/deployment/transport 和 route snapshot hash。

## Dependency outage

1. 数据库故障：停止写入和 worker；对象存储故障：停止上传、生成与提交；Redis 故障：保留数据库写入，暂停 dispatcher/worker。
2. 先恢复权威数据库，再验证对象引用；Redis 清空后从 queued stage 与 outbox 重建。
3. 依照[备份与灾难恢复](backup-and-disaster-recovery.md)执行；任何 hash mismatch 都是 blocker。
4. 恢复后执行只读校验、stub dry run 和可控恢复 job，再解除费用熔断。

## Phase B/A migration

数据导入、影子核对、分批切换和回滚按 [Phase B/A 到 Phase C 数据迁移 Runbook](phase-b-to-c-migration.md) 执行。源目录必须只读；任何 hash mismatch 或 unsupported schema 都不得切换。
