---
title: AITodo Obsidian-native 模式实施计划
type: plan
status: active
owner: TBD
created: 2026-04-15
updated: 2026-04-15
related_docs:
  - obsidian-native模式架构设计.md
  - obsidian-sync集成需求文档.md
  - obsidian-sync集成开发计划.md
tags:
  - aitodo
  - obsidian-native
  - plan
---

# AITodo Obsidian-native 模式实施计划

## 1. 目标

把 AITodo 从“数据库事实源 + Obsidian 投影”逐步演进为：

```text
Obsidian Markdown 事实源 + AITodo 缓存索引 + AITodo AI/MCP 网关
```

本计划不要求一次性删除 AITodo PostgreSQL，而是先让所有核心任务数据可从 Obsidian Markdown 重建。

## 2. 阶段拆解

| 阶段 | 目标 | 产出 |
| --- | --- | --- |
| P0 方案冻结 | 明确事实源、schema、读写策略 | 架构设计和实施计划 |
| P1 端到端导出验收 | 验证当前导出链路真实可用 | 手工验收记录 |
| P2 Markdown parser | 能从 Markdown 解析任务对象 | parser、测试、schema fixture |
| P3 远端索引器 | 能从 obsidianSync 快照和 pull 重建索引 | index service、缓存表 |
| P4 读 API 切换 | 查询可从 Obsidian 索引返回 | storage mode 配置 |
| P5 写 API 切换 | 创建/更新默认写 Obsidian | obsidian-native CRUD |
| P6 DB 降级 | DB 只保留缓存和运行态 | 重建工具、迁移说明 |

## 3. P1：当前导出链路手工验收

前置：

- `obsidianSync` 服务端文件 API 已实现。
- AITodo 导出服务已实现。
- 本地 Obsidian 插件可连接同一 `obsidianSync` 服务。

验收步骤：

1. 启动 `obsidianSync` API、PostgreSQL、MinIO。
2. 启动 AITodo API。
3. 配置 AITodo：

```env
OBSIDIAN_SYNC_BASE_URL=http://localhost:3000/api/v1
OBSIDIAN_SYNC_VAULT_ID=<vault-id>
OBSIDIAN_SYNC_ACCESS_TOKEN=<access-token>
```

4. 创建 AITodo 任务。
5. 调用：

```http
POST /api/v1/obsidian-sync/tasks/{task_id}/export
```

6. 本地 Obsidian 插件同步。
7. 核查 `AI-Todo/<记录类型>/<日期时间>.md` 出现且内容正确。

验收产物：

- `docs/summary/YYYY-MM-DD-obsidian-export-e2e-summary.md`

## 4. P2：Markdown parser

新增模块：

```text
app/services/obsidian_markdown_parser.py
```

能力：

- 解析 YAML front matter。
- 解析任务标题。
- 解析正文描述。
- 解析依赖 UUID。
- 兼容 `schema_version`。

测试：

- 标准任务文件。
- 无 due_at。
- 多 tags。
- depends_on。
- 非 AITodo 文件应跳过。

## 5. P3：远端索引器

新增模块：

```text
app/services/obsidian_index_service.py
```

能力：

1. 调用 `GET /files?prefix=AI-Todo/<记录类型>/`。
2. 对比 `contentHash`。
3. 下载变化文件。
4. 解析 Markdown。
5. 写入缓存表。

建议新增缓存表：

```text
obsidian_task_index
```

字段：

- `task_id`
- `vault_id`
- `path`
- `file_id`
- `version`
- `content_hash`
- `title`
- `description`
- `status`
- `priority`
- `due_at`
- `tags`
- `parent_id`
- `depends_on`
- `parsed_at`
- `source_updated_at`

## 6. P4：读 API 切换

新增配置：

```env
AITODO_STORAGE_MODE=database
```

取值：

- `database`：现有模式。
- `obsidian_native`：读接口优先从 `obsidian_task_index` 返回。

先切换只读接口：

- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /workspace/ready-to-start`
- `GET /workspace/suggested-today`

## 7. P5：写 API 切换

在 `obsidian_native` 模式下：

- `POST /tasks`：写 Obsidian Markdown，再刷新索引。
- `PUT/PATCH /tasks/{task_id}`：根据 binding version 写 Obsidian。
- `DELETE /tasks/{task_id}`：默认 archive，不立即 delete。

保留 database 模式，直到真实使用稳定。

## 8. P6：DB 降级与重建

提供命令或 API：

```text
rebuild_obsidian_index
```

能力：

1. 清空可重建索引。
2. 从 `obsidianSync` 快照重新下载解析。
3. 重建任务视图。

验收：

- 删除缓存表数据后能完整恢复任务列表。
- 关键查询结果一致。

## 9. 风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Markdown 被用户改坏 | 解析失败 | 标记 parse_error，不覆盖原文件 |
| 大量任务全量索引慢 | 查询延迟 | 增量 pull + contentHash 对比 |
| 双向写冲突 | 数据丢失风险 | 第一阶段 conflictStrategy=fail |
| front matter schema 演进 | 兼容问题 | `schema_version` + parser 兼容层 |

## 10. 下一步开发任务

1. 真实端到端手工验收当前导出链路。
2. 实现 `ObsidianMarkdownParser`。
3. 实现 `ObsidianSyncHttpClient` 的 list/read/download 能力。
4. 实现 `ObsidianIndexService`。
5. 增加 `AITODO_STORAGE_MODE` 配置。



## 11. P4 当前落地状态

已完成首批 `obsidian_native` 读模式开关：

- `GET /api/v1/tasks` 可从 `obsidian_task_index` 查询。
- `GET /api/v1/tasks/{task_id}` 可从 `obsidian_task_index` 查询。
- `GET /api/v1/workspace/ready-to-start` 可基于 `depends_on` 和索引状态计算。
- `GET /api/v1/workspace/suggested-today` 可基于索引任务评分。

默认 `AITODO_STORAGE_MODE=database` 不变，避免影响现有数据库事实源模式。


## 12. P5 当前落地状态

已完成首批 `obsidian_native` 写模式开关：

- `POST /api/v1/tasks` 可渲染 Markdown 并通过 obsidianSync 服务端文件 API 创建 `AI-Todo/<记录类型>/<日期时间>.md`。
- `PUT/PATCH /api/v1/tasks/{task_id}` 可读取 `obsidian_task_index` 的 version，传 `baseVersion` 更新远端 Markdown。
- 写入成功后同步更新 `obsidian_task_index` 并返回兼容 `TaskResponse` 的响应。

暂未切换删除语义；删除仍需先设计 archive 策略，避免误删扩散。


## 13. P5.2 当前落地状态

已完成 `obsidian_native` 安全删除策略：

- `DELETE /api/v1/tasks/{task_id}` 不调用 obsidianSync delete file。
- 删除会将任务 Markdown 更新为 `status: archived` 并写入 `archived_at`。
- `obsidian_task_index` 同步更新为 archived。
- 默认 `status_filter=open` 会排除 archived；可通过 `status_filter=archived` 查询归档任务。


## 14. P5.3 当前落地状态

已完成 `obsidian_native` 依赖关系写入：

- `POST /api/v1/tasks/{task_id}/dependencies` 会更新 `obsidian_task_index.depends_on` 并重写任务 Markdown。
- `GET /api/v1/tasks/{task_id}/dependencies` 会从 `depends_on` 返回兼容 `TaskDependencyListResponse` 的虚拟依赖记录。
- `DELETE /api/v1/tasks/{task_id}/dependencies/{dependency_id}` 支持删除虚拟依赖记录；`dependency_id` 为确定性 UUID，也兼容直接传 `depends_on_task_id`。
- MCP 的 add/list/remove dependency 工具也已支持 `obsidian_native` 分支。


## 15. P5.4 当前落地状态

已完成 `obsidian_native` 评论 / 时间线写入：

- `POST /api/v1/tasks/{task_id}/comments` 会把评论追加到 `obsidian_task_index.meta_data.timeline` 并重写任务 Markdown。
- `GET /api/v1/tasks/{task_id}/timeline` 会从 `meta_data.timeline` 返回兼容 `TaskCommentListResponse` 的虚拟评论记录。
- Markdown 的 `## 时间线` 区块会随评论更新。
- MCP 的 `add_task_comment`、`get_task_timeline` 也已支持 `obsidian_native` 分支。


## 16. P5.5 当前落地状态

已完成 `obsidian_native` 工作台查询补齐：

- `GET /api/v1/workspace/today`
- `GET /api/v1/workspace/overdue`
- `GET /api/v1/workspace/blocked`
- `GET /api/v1/workspace/recently-updated`
- `GET /api/v1/workspace/stale`
- `GET /api/v1/workspace/alerts`
- `GET /api/v1/workspace/dashboard`

上述接口在 `AITODO_STORAGE_MODE=obsidian_native` 时会从 `obsidian_task_index` 读取或聚合；默认 database 模式保持不变。


## 17. P5.6 当前落地状态

已完成 `obsidian_native` 自然语言解析入库：

- `POST /api/v1/tasks/parse-and-create` 在 native 模式下会复用 `TaskParsingService` 解析文本。
- 置信度门槛、force_create、candidate selection 和 override 规则保持兼容。
- 创建时调用 `ObsidianNativeTaskWriteService` 写入 Markdown 并更新 `obsidian_task_index`。
- MCP 的 `parse_and_create_task` 也已支持 `obsidian_native` 分支。


## 18. P5.7 当前落地状态

已完成 `obsidian_native` 计划生成与应用：

- `POST /api/v1/tasks/{task_id}/plan` 会从 `obsidian_task_index` 读取任务并生成结构化计划。
- `POST /api/v1/tasks/{task_id}/apply-plan` 会将计划项创建为 Obsidian Markdown 子任务。
- 子任务会写入 `parent_id`，计划项依赖会写入 `depends_on` 并重写 Markdown。
- MCP 的 `plan_task_execution`、`apply_task_plan` 也已支持 `obsidian_native` 分支。


## 19. P5.8 当前落地状态

已新增 Obsidian-native smoke 联调脚本：

```bash
scripts/smoke-obsidian-native.py
```

脚本会验证：

1. `parse-and-create` 创建 native task。
2. 评论写入时间线。
3. 计划生成。
4. 应用计划创建子任务。
5. dashboard 聚合可读。
6. 可选通过 obsidianSync 文件 API 校验 Markdown 文件存在。

该脚本用于真实服务联调，不替代单元测试。


## 20. P5.9 当前落地状态

已新增一键本地 E2E 联调脚本：

```bash
scripts/e2e-obsidian-native-local.py
```

该脚本会自动：

1. 启动 obsidianSync PostgreSQL / MinIO。
2. 运行 obsidianSync migration。
3. 启动 obsidianSync API。
4. 登录并创建测试 Vault。
5. 创建临时 AITodo SQLite 数据库并迁移。
6. 启动 AITodo API 的 `obsidian_native` 模式。
7. 执行 `scripts/smoke-obsidian-native.py` 并通过 obsidianSync 文件 API 校验 Markdown 文件存在。

该脚本用于本地端到端验证，不用于生产部署。
