# Phase B/A 到 Phase C 数据迁移 Runbook

Owner：`application-oncall` 负责导入器与报告，`platform-oncall` 负责 PostgreSQL、对象存储和只读挂载，`security-oncall` 处理秘密或恶意文件告警。迁移窗口内必须记录批次、租户、源快照、镜像 digest、报告路径、blocker、审批人和回滚决定。

## 不可突破的边界

- Phase A/B 原目录只读挂载到 `/migration-source`。迁移工具不得修改、重命名、删除或“修复”源文件。
- `.env`、锁文件、缓存、Git 和 `node_modules` 不进入对象存储；但它们参与源目录快照，迁移过程中被修改会阻断切换。
- `job_manifest/v2`、source manifest、revision metadata、artifact index 和所有声明哈希必须先验证。
- 任一 hash mismatch、unsupported schema、符号链接、特殊文件、父 revision 缺失或源快照变化都是 blocker。
- 禁止通过重算并覆盖源记录来消除 blocker。修复必须发生在迁移窗口之外，由数据 owner 形成新的、可审计的 Phase B revision。
- Phase C 数据库与对象只能前向修复；回滚只切换读取路径，不删除已经导入的数据。

## 前置检查

1. 固定应用镜像 digest、数据库 schema version 和对象存储 bucket/versioning 策略。
2. 对 PostgreSQL 和对象存储执行一次可恢复备份，保留对应报告。
3. 将源目录配置为宿主机绝对路径：

   ```bash
   export CASE_VIDEO_MIGRATION_SOURCE=/srv/case-video/phase-b-jobs
   ```

4. 确认 Compose 展开后的 `/migration-source` 为 `read_only: true`，`/release-evidence` 可写。
5. 按租户或创建时间准备批次清单；首批只选择可人工复核的小样本，不直接全量切换。

## 第一步：只读 dry-run

```bash
docker compose --profile operations run --rm legacy-migration-dry-run
```

报告写入 `/release-evidence/migration-dry-run.json`。每个 job 必须包含：

- `source_count`
- `revision_count`
- `artifact_count`
- `total_bytes`
- `hash_mismatch`
- `unsupported_schema`
- `source_snapshot_sha256`
- `final_status`

只有 `final_status=validated`、`hash_mismatch=false`、`unsupported_schema=false` 且 `errors=[]` 的 job 可以进入导入批次。dry-run 不创建 tenant、job、artifact、审计记录或对象。

## 第二步：抽样与分批导入

```bash
docker compose --profile operations run --rm legacy-migration-import
```

报告写入 `/release-evidence/migration-import.json`。导入器使用完整文件 inventory 生成确定性 revision ID，重复执行同一批次必须复用同一对象与 revision，不产生第二份当前版本。

每个导入 job 只有同时满足以下条件才算完成：

- `final_status=imported`
- `shadow_status=passed`
- `database_artifact_count=artifact_count`
- `object_verified_count=artifact_count`
- PostgreSQL manifest 的规范化哈希等于源 manifest 哈希
- PostgreSQL 中每个 artifact 的名称、大小和 sha256 与源快照一致
- 对象存储实际流式读取后的大小和 sha256 与源快照一致

任何失败 job 保持旧读取路径，不进入切换集合。成功与失败 job 可以处于同一批次，但切换清单必须逐 job 生成，不能按“批次命令退出成功”整体放行。

## 第三步：独立影子核对

正式切换前重新从只读源执行：

```bash
docker compose --profile operations run --rm legacy-migration-shadow
```

报告写入 `/release-evidence/migration-shadow.json`。该步骤不导入、不改数据库，只比较当前源快照、数据库记录和对象实际字节。只有 `final_status=verified` 且 `shadow_status=passed` 的 job 可以进入 Phase C 读路径。

如果源文件在导入后发生变化，revision ID 或 manifest 哈希会变化，shadow-only 必须阻断。先暂停该 job 的 Phase B 写入，再重新走 dry-run、导入和影子核对；不得沿用旧报告。

## 第四步：切换

1. 按租户或 job 白名单切换 Phase C 读取，不做全局瞬时切换。
2. 每批先切只读访问，验证列表、详情、revision、artifact 下载、SSE 和权限隔离。
3. 再为该批启用 Phase C 写入；旧目录继续只读。
4. 观察至少一个业务峰值窗口：API 错误、对象 404/hash mismatch、队列年龄、dead letter、跨租户拒绝和费用异常均不得恶化。
5. 保存三份报告、批次清单、应用/engine digest 和操作者审计记录。

## 回滚

出现 manifest 不一致、对象不可读、权限越界或写入错误时：

1. 停止该批 Phase C 新写入和 worker 领取；不删除 outbox、数据库行或对象。
2. 将受影响 job 的读取白名单切回只读 Phase B 路径。
3. 保留 Phase C 数据用于比对，记录最后一个成功 request/trace ID 和失败对象 key 的哈希元数据；不要记录签名 URL 或材料内容。
4. 采用前向修复后重新 dry-run、导入、shadow-only，再逐 job 恢复切换。

Phase B 原始只读快照至少保留一个完整数据保留周期。保留窗口结束前必须完成全量 shadow-only、备份恢复演练和业务 owner 签字，之后才可单独审批退役旧读取路径。

## 验收记录

迁移发布门要求：

- dry-run、抽样导入、全量导入和最终 shadow-only 报告均归档。
- 所有 blocker 清零或明确排除在切换清单之外。
- 至少抽查一个含 source manifest、一个含 revision 链、一个含 artifact index 的 job。
- 对象字节篡改演练能被 shadow-only 阻断。
- dry-run 的数据库审计确认零写入。
- 回滚演练证明可切回旧只读路径，且 Phase C 数据未被删除。
