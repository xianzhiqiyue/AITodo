---
title: Obsidian-native 生产上线总结
type: summary
status: active
owner: TBD
created: 2026-04-16
updated: 2026-04-16
related_docs:
  - ../obsidian-native模式架构设计.md
  - ../obsidian-native模式实施计划.md
  - ../obsidian-sync集成需求文档.md
  - ../运维与排障.md
  - ../../README.md
  - ../../../obsidianSync/docs/AITodo接入服务端文件API设计.md
tags:
  - aitodo
  - obsidian-native
  - production-rollout
  - summary
---

# Obsidian-native 生产上线总结

## 1. 上线结论

2026-04-16 已将 AITodo 与 obsidianSync 的 Obsidian-native 链路部署到正式服务器，并完成真实生产 smoke 验证和本地 Obsidian 可见性验证。

当前结论：

```text
AITodo -> obsidianSync 服务端文件 API -> main-vault -> 本地 Obsidian
```

链路已打通。

## 2. 服务器与服务

服务器：

```text
阿里云 47.122.112.210
```

服务部署位置：

```text
obsidianSync: /home/admin/obsidianSync
AITodo:       /opt/ai-todo-server
```

服务端口：

```text
obsidianSync sync-api: 3000
AITodo API:             8000
MinIO API:              9000
obsidianSync Postgres:  127.0.0.1:5432
```

## 3. Vault 配置

AITodo 当前写入目标：

```text
Vault 名称：main-vault
Vault ID：08d02552-8321-40c0-923a-22768c33d854
```

AITodo 容器内当前关键配置：

```env
AITODO_STORAGE_MODE=obsidian_native
OBSIDIAN_SYNC_BASE_URL=http://172.21.0.1:3000/api/v1
OBSIDIAN_SYNC_VAULT_ID=08d02552-8321-40c0-923a-22768c33d854
```

说明：`172.21.0.1` 是 AITodo 容器访问宿主机 obsidianSync `:3000` 的 Docker 网关地址。

## 4. 已部署能力

AITodo `obsidian_native` 模式已覆盖：

- `POST /api/v1/tasks`
- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `PUT/PATCH /api/v1/tasks/{task_id}`
- `DELETE /api/v1/tasks/{task_id}`：安全归档为 `status: archived`
- `POST /api/v1/tasks/parse-and-create`
- `POST/GET/DELETE /api/v1/tasks/{task_id}/dependencies`
- `POST /api/v1/tasks/{task_id}/comments`
- `GET /api/v1/tasks/{task_id}/timeline`
- workspace today / overdue / blocked / ready-to-start / recently-updated / suggested-today / stale / alerts / dashboard
- `POST /api/v1/tasks/{task_id}/plan`
- `POST /api/v1/tasks/{task_id}/apply-plan`
- `POST /api/v1/obsidian-sync/index/rebuild`
- `GET /api/v1/obsidian-sync/index/tasks`

obsidianSync 已部署服务端文件 API：

- `GET /api/v1/vaults/{vaultId}/files`
- `GET /api/v1/vaults/{vaultId}/files/by-path/{path}`
- `PUT /api/v1/vaults/{vaultId}/files/by-path/{path}`
- `DELETE /api/v1/vaults/{vaultId}/files/by-path/{path}`

## 5. 生产验证结果

### 5.1 健康检查

obsidianSync：

```json
{"status":"ok","service":"sync-api"}
```

```json
{"status":"ready"}
```

AITodo：

```json
{
  "status": "healthy",
  "database": "connected",
  "migration": "006",
  "parsing_service": "heuristic_only",
  "embedding_service": "disabled",
  "version": "1.1.0"
}
```

### 5.2 Smoke 结果

生产 smoke 执行成功：

```text
SMOKE OK
```

生成任务：

```text
task_id: 65f6719f-b621-4d94-b734-db1790f54d44
sub_task_id: e0c8d112-4738-49fb-bdda-deb5f6faca24
```

obsidianSync 文件 API 校验：

```text
obsidianSync verified fileId=5a306850-57c1-4aa2-a21d-ecb664f25b86
```

### 5.3 本地 Obsidian 验证

用户已确认本地 Obsidian 中看到 AITodo 写入的文件，说明：

```text
AITodo -> obsidianSync -> 本地 Obsidian
```

真实同步链路可用。

## 6. 部署过程记录

### 6.1 obsidianSync

- 已部署新增文件 API。
- 已修复 refresh token 同秒重复问题：JWT payload 增加随机 `jti`。
- 已验证 `/health`、`/ready`、文件 API 路由鉴权行为。

### 6.2 AITodo

- 已部署新增代码和 Alembic migration。
- 数据库迁移到 `006`。
- 初次 Docker build 因远端 pip 下载过慢超时；已采用容器热更新 + `docker commit` 固化当前可运行镜像的方式完成上线。
- 当前本地镜像标签：

```text
ai-todo-server-ai-todo-api:latest
```

当前镜像 ID：

```text
8088fe82cbc5
```

部署前备份：

```text
/opt/deploy-backups/ai-todo-server-20260416084824.tar.gz
```

## 7. 已知风险

1. AITodo 当前镜像通过容器热更新后 commit 固化，后续应在服务器网络稳定时重新执行 `docker compose build`，让镜像构建路径也完全验证。
2. 当前 AITodo 使用 obsidianSync 账号密码自动登录获取 token；后续建议改为 refresh token 加密存储或服务账号机制。
3. 本地 Obsidian 修改回写 AITodo 仍未实现；当前主要是 AITodo 写入 Obsidian 并通过索引读取。
4. 删除采用 `status: archived`，不会远端硬删文件，这是刻意的安全策略。
5. smoke 产生的测试文件仍在 `main-vault` 中，可按归档策略保留或清理。

## 8. 回滚方式

如需回滚到旧数据库事实源模式：

1. 修改 `/opt/ai-todo-server/docker-compose.yml`：

```env
AITODO_STORAGE_MODE=database
```

2. 重启 AITodo：

```bash
cd /opt/ai-todo-server
docker compose up -d ai-todo-api
```

3. 验证：

```bash
curl -fsS http://127.0.0.1:8000/health
```

说明：已执行的 Alembic 005/006 是向后兼容新增表，不影响 database 模式。

## 9. 后续建议

1. 观察 24 小时生产日志。
2. 重新执行一次正式 `docker compose build ai-todo-api`，替代热更新镜像路径。
3. 增加定时 smoke 或健康探针，验证 AITodo -> obsidianSync 写入链路。
4. 设计 Obsidian 本地修改回写 AITodo 的冲突策略。
5. 梳理并归档 smoke 测试任务。
