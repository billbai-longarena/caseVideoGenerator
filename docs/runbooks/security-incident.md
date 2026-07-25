# Case Video 安全事件 Runbook

Owner：`security-oncall`；平台值班协同。严重事件先隔离与保全证据，再恢复业务。不得在工单或聊天中复制密钥、令牌、source、prompt、签名 URL 或完整模型响应。

## Authentication anomaly

1. 核对入口源、OIDC issuer/audience、JWT 时钟、令牌类型和失败路由模板。
2. 疑似暴力尝试时在 WAF/IdP 限流并吊销相关 client/session；不要放宽 nonce、签名或 expiry 校验。
3. 疑似密钥泄漏时轮换 secret manager 中凭据，重启工作负载并撤销旧值；检查 Git、镜像层和日志扫描结果。
4. 验证合法用户登录、服务账号最小 scope、401 恢复到基线，并记录时间线和受影响账号范围。

## Authorization anomaly

1. 检查角色/成员最近变更和跨租户 ID 枚举；指标仅用于趋势，具体主体从受控审计查询。
2. 冻结可疑 session、签名下载和危险管理操作；保留不可变审计。
3. 修复 membership、tenant claim 或 repository tenant filter，禁止仅在 UI 隐藏资源。
4. 重跑 ID 枚举、SSE、revision、artifact、签名 URL 和后台任务的跨租户测试。

## Malicious upload or secret detection

1. 隔离 upload/object，不允许 worker 读取；记录 hash、检测规则和关联 job，不打开未知文件。
2. 取消相关 stage 并检查同 hash 是否出现在其他租户；查询必须遵循租户权限。
3. 更新扫描规则、轮换暴露凭据、清理派生对象，保留 legal hold 所需证据。
4. 验证 MIME、路径穿越、压缩炸弹、恶意软件和秘密扫描测试均阻断。
