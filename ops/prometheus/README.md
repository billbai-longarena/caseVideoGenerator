# Prometheus 与告警部署

生产部署前必须完成以下替换和验证：

1. 将只具备 `worker.execute`/metrics 读取权限的服务账号令牌挂载到 `/run/secrets/case_video_metrics_token`，不得把令牌写入仓库、镜像或 Prometheus 配置。
2. 将 `case-video-alerts.yml` 中相对 `runbook_url` 通过 Alertmanager/入口代理补全为本环境公开运维域名；目标页面对应 `docs/runbooks/`。
3. 复制 `ops/alertmanager/alertmanager.example.yml` 到部署系统的 secret/config 管理中，替换所有 `.invalid` 地址后再启用；示例文件本身不得直接用于生产通知。
4. 运行 `promtool check config` 和 `promtool check rules`，再人为制造一次测试告警，验证通知 owner、恢复通知和 runbook 链接。

指标标签只允许 route、provider、queue、status/state、method 和路由模板等有限枚举。禁止加入 `tenant_id`、`job_id`、`worker_id`、对象 key、邮箱或签名 URL。
