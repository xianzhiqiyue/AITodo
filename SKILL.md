---
name: aitodo
version: 0.2.0
description: AI-first 任务中枢后端，提供 REST/MCP 任务管理、规划、通知、工作台与 Obsidian-native Markdown 集成能力。
author: Zhuyue <zhuyue314@gmail.com>
category: productivity
tags:
  - api
  - mcp
  - backend
  - integration
---

# AITodo Skill

此项目是一个可交付给 AI 助手调用的任务管理 Skill：

- FastAPI 后端服务，支持任务 CRUD 与状态机。
- 自然语言任务解析与确认入库。
- 任务拆解、计划生成、计划应用、依赖关系与执行建议。
- Workspace 聚合视图、今日建议、逾期/阻塞/停滞任务视图与告警。
- 评论 / 时间线 / 系统事件。
- MCP 服务与多渠道通知。
- Obsidian Sync 集成：可将任务写入 Obsidian Vault Markdown，并从 Obsidian Markdown 重建索引。
- Obsidian-native 模式：以 Obsidian Markdown 为任务事实源，AITodo 数据库作为可重建索引和运行态缓存。

## 运行策略（必须遵守）

- **默认使用线上部署服务器**：默认 AITodo API 为 `http://47.122.112.210:8000`。
- **默认连接 Obsidian**：用户未明确指定保存位置时，默认写入生产 `main-vault`，即走线上 AITodo 的 Obsidian-native 链路，把 Obsidian Markdown 作为事实源。
- **只有用户明确说“保存在 AITodo / 保存在 aitodo 服务器 / 不写 Obsidian”时**，才把 AITodo 服务器自身作为保存目标；即便如此，也必须调用线上 AITodo 服务器，不回退到本地服务。

## 快速上手

`/api/v1` 下的 REST 接口和 MCP 工具默认复用线上部署服务能力。

服务健康检查：

```bash
curl http://47.122.112.210:8000/health
```

MCP Server：

```bash
python mcp_server.py
```

## 存储模式

默认保存策略：

```env
AITODO_BASE_URL=http://47.122.112.210:8000
AITODO_STORAGE_MODE=obsidian_native
```

线上 Obsidian-native 配置：

```env
AITODO_STORAGE_MODE=obsidian_native
OBSIDIAN_SYNC_BASE_URL=http://172.21.0.1:3000/api/v1
OBSIDIAN_SYNC_VAULT_ID=08d02552-8321-40c0-923a-22768c33d854
OBSIDIAN_SYNC_EMAIL=<email>
OBSIDIAN_SYNC_PASSWORD=<password>
# 或使用短期 access token：
# OBSIDIAN_SYNC_ACCESS_TOKEN=<access-token>
```

生产当前已验证目标 Vault：

```text
main-vault
08d02552-8321-40c0-923a-22768c33d854
```

容器内访问同机 obsidianSync 时，`OBSIDIAN_SYNC_BASE_URL` 应使用 Docker 网关地址，而不是容器内 `127.0.0.1`。

## REST 能力概览

### 任务主链路

- `POST /api/v1/tasks`：创建任务。
- `GET /api/v1/tasks`：查询任务。
- `GET /api/v1/tasks/{task_id}`：查询单任务。
- `PUT/PATCH /api/v1/tasks/{task_id}`：更新任务。
- `DELETE /api/v1/tasks/{task_id}`：database 模式删除；Obsidian-native 模式安全归档为 `status: archived`。
- `POST /api/v1/tasks/parse`：自然语言解析为草稿。
- `POST /api/v1/tasks/parse-and-create`：自然语言解析并创建任务；Obsidian-native 模式会写入 Markdown。

### 计划与拆解

- `GET /api/v1/tasks/{task_id}/decompose/suggestions`：生成拆解建议。
- `POST /api/v1/tasks/{task_id}/decompose/apply-suggestions`：应用拆解建议。
- `POST /api/v1/tasks/{task_id}/plan`：生成结构化执行计划。
- `POST /api/v1/tasks/{task_id}/apply-plan`：应用计划；Obsidian-native 模式会创建 Markdown 子任务并维护 `parent_id` / `depends_on`。

### 依赖与时间线

- `POST /api/v1/tasks/{task_id}/dependencies`：添加依赖；Obsidian-native 模式维护 Markdown front matter 的 `depends_on`。
- `GET /api/v1/tasks/{task_id}/dependencies`：查询依赖。
- `DELETE /api/v1/tasks/{task_id}/dependencies/{dependency_id}`：移除依赖。
- `POST /api/v1/tasks/{task_id}/comments`：添加评论；Obsidian-native 模式写入 `meta_data.timeline` 并重写 Markdown `## 时间线`。
- `GET /api/v1/tasks/{task_id}/timeline`：查询时间线。

### 工作台

- `GET /api/v1/workspace/today`
- `GET /api/v1/workspace/overdue`
- `GET /api/v1/workspace/blocked`
- `GET /api/v1/workspace/ready-to-start`
- `GET /api/v1/workspace/recently-updated`
- `GET /api/v1/workspace/suggested-today`
- `GET /api/v1/workspace/stale`
- `GET /api/v1/workspace/alerts`
- `GET /api/v1/workspace/dashboard`

Obsidian-native 模式下，上述查询会从 `obsidian_task_index` 读取或聚合。

### Obsidian Sync / Obsidian-native

- `POST /api/v1/obsidian-sync/tasks/{task_id}/export`：将已有 database 任务导出为 Obsidian Markdown。
- `POST /api/v1/obsidian-sync/export-all`：批量导出任务。
- `GET /api/v1/obsidian-sync/bindings`：查询 AITodo 实体与 Obsidian 文件绑定。
- `POST /api/v1/obsidian-sync/index/rebuild`：从 Obsidian Sync 文件快照下载并解析 Markdown，重建索引。
- `GET /api/v1/obsidian-sync/index/tasks`：查询已重建的 Obsidian 任务索引。

## MCP 工具概览

核心工具：

- `upsert_task`
- `get_task_context`
- `delete_task`
- `decompose_task`
- `parse_task_input`
- `parse_and_create_task`
- `add_task_dependency`
- `list_task_dependencies`
- `remove_task_dependency`
- `add_task_comment`
- `get_task_timeline`
- `get_workspace_today`
- `get_workspace_overdue`
- `get_workspace_blocked`
- `get_workspace_recently_updated`
- `get_workspace_alerts`
- `get_workspace_dashboard`
- `get_ready_to_start_tasks`
- `get_suggested_today_tasks`
- `get_stale_tasks`
- `plan_task_execution`
- `apply_task_plan`
- `scan_reminders`
- `dispatch_alert_notifications`
- `get_task_recovery_suggestions`
- `get_review_summary`
- `test_notification_channel`

Obsidian 工具：

- `export_task_to_obsidian`：将单个任务导出到 Obsidian Vault 的 `AI-Todo/<记录类型>/<日期时间>.md`。
- `export_all_tasks_to_obsidian`：批量导出任务到 Obsidian Vault。
- `rebuild_obsidian_task_index`：从 Obsidian Sync 文件快照下载并解析 `AI-Todo/<记录类型>/` Markdown，重建查询索引。
- `list_obsidian_indexed_tasks`：读取已重建的 Obsidian 任务索引。

部分 MCP 工具会根据 `AITODO_STORAGE_MODE` 自动切换 database / obsidian_native 分支。

## Obsidian Markdown 约定

任务文件默认路径：

```text
AI-Todo/<记录类型>/<日期时间>.md
```

记录类型包括：`工作日记`、`待办任务`、`其他事项`、`学习感悟`。文件名只使用日期时间，例如 `2026-04-16 11-30-25-123.md`。稳定任务 ID 保存在 front matter 的 `aitodo_id` 中。

front matter 示例：

```yaml
---
source: ai-todo
schema_version: 1
aitodo_id: <task_id>
status: todo
priority: 3
due_at:
parent_id:
tags: []
depends_on: []
updated_at: <iso8601>
archived_at:
---
```

正文包含标题、描述、依赖区块和时间线区块。

## 联调脚本

生产 smoke：

```bash
scripts/smoke-obsidian-native.py
```

一键本地 E2E（仅维护者本地开发/回归，不作为 Skill 默认执行路径）：

```bash
scripts/e2e-obsidian-native-local.py
```

脚本会覆盖从自然语言创建、评论、计划、计划应用、dashboard 到 obsidianSync 文件校验的核心链路。

## 运维与回滚

生产上线总结：

```text
docs/summary/2026-04-16-obsidian-native-production-rollout-summary.md
```

运维与回滚说明：

```text
docs/运维与排障.md
```

快速回滚到 database 模式：

```env
AITODO_STORAGE_MODE=database
```

然后重启 AITodo API。
