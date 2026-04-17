---
title: AITodo Obsidian-native 模式架构设计
type: architecture
status: active
owner: TBD
created: 2026-04-15
updated: 2026-04-15
related_docs:
  - ../SOP.md
  - obsidian-sync集成需求文档.md
  - obsidian-sync集成开发计划.md
  - ../../obsidianSync/docs/AITodo接入服务端文件API设计.md
tags:
  - aitodo
  - obsidian-native
  - obsidian-sync
  - architecture
---

# AITodo Obsidian-native 模式架构设计

## 1. 结论

下一阶段不应删除 AITodo 服务，而应把目标调整为：

```text
obsidianSync = 存储与同步层
Obsidian Markdown = 可选主事实源
AITodo = AI 任务业务层 / MCP 网关 / Markdown 读写器 / 可重建索引缓存
```

也就是说：

- AITodo **不实现同步能力**。
- AITodo **通过 obsidianSync 服务端文件 API 读写 Obsidian Vault**。
- AITodo 服务仍保留，用于 AI 解析、任务规划、MCP、查询聚合、通知和索引。
- AITodo 数据库逐步从“主事实源”降级为“缓存 / 索引 / 运行态”，核心事实可由 Obsidian Markdown 重建。

## 2. 架构目标

1. 让 Obsidian Vault 中的 Markdown 文件成为任务数据的长期可读、可迁移载体。
2. 让 `obsidianSync` 继续负责多端同步、版本、对象存储和 checkpoint。
3. 让 AITodo 保留 Agent 友好的业务 API / MCP 能力。
4. 让 AITodo DB 中的数据尽量可从 Obsidian Markdown 重建。
5. 避免在 AITodo 内重复实现同步协议。

## 3. 模式对比

| 模式 | 事实源 | AITodo DB 角色 | 优点 | 风险 |
| --- | --- | --- | --- | --- |
| 当前投影模式 | AITodo PostgreSQL | 主库 | 任务逻辑强、查询快 | 与 Markdown 双写一致性 |
| Obsidian-native 模式 | Obsidian Markdown | 缓存 / 索引 | 单一可读事实源、迁移友好 | 需要解析、索引和冲突策略 |
| 无 AITodo 服务 | Obsidian Markdown | 无 | 极简 | 失去 MCP、推荐、通知和复杂查询 |

推荐演进到 **Obsidian-native 模式**，而不是直接删除 AITodo 服务。

## 4. 目标架构

```text
Agent / REST / MCP
       |
       v
+-----------------------------+
| AITodo Service              |
| - Markdown schema           |
| - task parser / planner     |
| - MCP tools                 |
| - query index / cache       |
| - notification jobs         |
+-------------+---------------+
              |
              | server file API
              v
+-----------------------------+
| obsidianSync Sync API       |
| - files by path             |
| - object store              |
| - file versions             |
| - change events             |
| - checkpoint                |
+-------------+---------------+
              |
              | sync/pull
              v
+-----------------------------+
| Local Obsidian Vault        |
| - AI-Todo/<记录类型>/*.md        |
| - user-readable markdown    |
+-----------------------------+
```

## 5. 数据分层

### 5.1 Obsidian Markdown：长期事实层

保存：

- 任务标题
- 描述
- 状态
- 优先级
- 截止时间
- 标签
- 父子关系
- 依赖关系
- 评论 / 时间线
- AI 元信息

默认路径：

```text
AI-Todo/<记录类型>/<日期时间>.md
AI-Todo/comments/<task_id>.md
AI-Todo/dashboards/*.md
AI-Todo/index.md
```

### 5.2 obsidianSync：同步存储层

保存：

- 文件元数据
- 文件版本
- 内容 hash
- change events
- checkpoint
- tombstone
- S3/MinIO 对象

AITodo 不直接读取或修改这些表，只通过 API。

### 5.3 AITodo DB：缓存 / 索引 / 运行态

保留：

- `obsidian_sync_connections`
- `obsidian_file_bindings`
- 解析后的任务索引缓存
- embedding / 搜索索引
- 通知发送记录
- 后台任务状态
- 最近错误与重试状态

逐步弱化：

- `tasks` 作为唯一主事实源的地位。
- `task_dependencies` / `task_comments` 的不可重建性。

## 6. Markdown schema 设计

任务文件 front matter：

```yaml
---
source: ai-todo
schema_version: 1
aitodo_id: 550e8400-e29b-41d4-a716-446655440000
status: todo
priority: 3
due_at:
parent_id:
depends_on:
  - 11111111-1111-1111-1111-111111111111
tags:
  - work
created_at: 2026-04-15T10:00:00+08:00
updated_at: 2026-04-15T14:30:00+08:00
---
```

正文：

```md
# 任务标题

任务描述。

## 子任务

- [[AI-Todo/<记录类型>/<child_task_id>.md]]

## 依赖

- [[AI-Todo/<记录类型>/<dependency_task_id>.md]]

## 时间线

- 2026-04-15T14:30:00+08:00 [progress] 已开始处理
```

规则：

1. front matter 是机器解析事实源。
2. 正文优先服务人类阅读。
3. `schema_version` 必须存在，用于后续迁移。
4. `aitodo_id` 是稳定 ID，不随文件 rename 变化。
5. 依赖关系使用 UUID + Wiki link 双表达，机器以 UUID 为准。

## 7. 读取策略

### 7.1 冷启动重建索引

1. 调用 `obsidianSync` 文件快照 API：

```http
GET /vaults/{vaultId}/files?prefix=AI-Todo/<记录类型>/
```

2. 对比本地 `obsidian_file_bindings`。
3. 下载缺失或 contentHash 变化的 Markdown。
4. 解析 front matter 和正文。
5. 更新 AITodo 索引缓存。

### 7.2 增量更新

1. AITodo 保存最近 checkpoint。
2. 调用 `sync/pull?fromCheckpoint=<last_checkpoint>`。
3. 过滤 `AI-Todo/` 路径。
4. 对 create/update 下载并解析文件。
5. 对 delete 标记索引删除。
6. 更新 checkpoint。

### 7.3 查询

默认查询走 AITodo 缓存索引；当发现缓存过期或 binding 缺失时，按需从 Obsidian Sync 读取并修复。

## 8. 写入策略

### 8.1 创建任务

1. AITodo 生成 UUID。
2. 渲染 Markdown。
3. 调用 `PUT /files/by-path/AI-Todo/<记录类型>/<日期时间>.md`。
4. 保存 binding 和解析缓存。

### 8.2 更新任务

1. 读取 binding 的 `version`。
2. 渲染新 Markdown。
3. 调用 `PUT /files/by-path/...`，传 `baseVersion`。
4. 成功后更新 binding 和缓存。

### 8.3 删除任务

默认两种策略：

- `archive`：移动或改状态为 archived，保留文件。
- `delete`：调用 `DELETE /files/by-path/...`，由 obsidianSync 写 tombstone。

第一阶段推荐 `archive`，避免误删扩散。

## 9. 冲突策略

第一阶段：

- `conflictStrategy=fail`
- AITodo 不自动覆盖 Obsidian 本地编辑。
- 发生 `VERSION_CONFLICT` 时：
  1. 拉取远端最新 Markdown。
  2. 解析为候选任务。
  3. 标记本地索引为 conflict。
  4. 暂停该任务自动导出。

后续可支持：

- AITodo wins
- Obsidian wins
- 自动三方合并
- 生成 `.conflict.md`

## 10. 保留 AITodo 服务的原因

即使 Obsidian Markdown 成为事实源，AITodo 服务仍负责：

1. MCP tools。
2. REST API。
3. 自然语言解析。
4. AI 任务拆解与计划。
5. ready-to-start / suggested-today / stale / blocked 查询。
6. 通知和定时扫描。
7. Markdown 解析缓存。
8. 向量搜索和 embedding。
9. 冲突检测和恢复工作流。

这些能力不应塞进 `obsidianSync`，因为 `obsidianSync` 的职责是文件同步，不是任务业务。

## 11. 分阶段演进

### P0：当前状态

- AITodo DB 是事实源。
- Obsidian Markdown 是导出投影。

### P1：Obsidian 写入稳定

- 当前已开始：AITodo 能导出任务到 `obsidianSync`。
- 继续补真实端到端手工验证。

### P2：Obsidian 读取与索引

- AITodo 新增从 `obsidianSync` 读取文件快照和下载 Markdown 的能力。
- 新增 Markdown parser。
- 新增索引刷新接口。

### P3：事实源切换开关

新增配置：

```env
AITODO_STORAGE_MODE=database|obsidian_native
```

- `database`：当前模式。
- `obsidian_native`：Obsidian Markdown 为主，AITodo DB 为缓存。

### P4：弱化本地 tasks 主表

- 任务 CRUD 默认写 Obsidian。
- DB 缓存异步刷新。
- 支持从 Markdown 全量重建。

## 12. 验收标准

1. 可以从 Obsidian Vault 重建 AITodo 任务索引。
2. 新建 / 更新任务以 Markdown 为主事实。
3. AITodo API 查询结果来自可重建索引。
4. 删除本地缓存后可从 Obsidian 恢复任务视图。
5. 冲突不会静默覆盖用户本地编辑。
6. `obsidianSync` 仍不理解 AITodo 业务，只提供文件能力。

