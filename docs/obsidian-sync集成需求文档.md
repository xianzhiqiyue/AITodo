---
title: AITodo 与 Obsidian Sync 集成需求文档
type: requirements
status: active
owner: TBD
created: 2026-04-15
updated: 2026-04-15
related_docs:
  - ../SOP.md
  - ../README.md
  - v1.2-需求文档.md
  - v1.2-架构设计文档.md
  - obsidian-sync集成开发计划.md
  - ../../obsidianSync/SOP.md
  - ../../obsidianSync/docs/API设计.md
  - ../../obsidianSync/docs/AITodo接入服务端文件API设计.md
tags:
  - aitodo
  - obsidian-sync
  - integration
  - requirements
---

# AITodo 与 Obsidian Sync 集成需求文档

## 1. 背景

AITodo 当前是面向 AI Agent 的任务中心后端，主要通过 REST API 与 MCP 工具管理任务、依赖、评论、提醒和工作台视图。用户希望后续将 AITodo 数据同步到自建 Obsidian Vault 中，使任务能以 Markdown 文件形式出现在本地 Obsidian，并继续由 `obsidianSync` 的多端同步能力分发到桌面和移动端。

`obsidianSync` 当前已具备：

- Vault、设备、用户鉴权。
- 基于 checkpoint 的增量同步。
- PostgreSQL 元数据和 S3/MinIO 对象存储。
- `prepare -> upload object -> commit -> pull` 的同步协议。

但该协议偏插件同步客户端，不适合 AITodo 这类服务端系统直接按 path 写文件。因此本期采用长期路线：先在 `obsidianSync` 增加服务端对服务端友好的文件 API，再由 AITodo 调用这些 API。

## 2. 目标

1. AITodo 能把任务、评论、工作台摘要导出为 Obsidian Vault 中的 Markdown 文件。
2. 写入后的文件能通过 `obsidianSync` 正常同步到本地 Obsidian。
3. AITodo 不直接写 `obsidianSync` 的 PostgreSQL 或对象桶，只通过 API 接入。
4. AITodo 能保存任务与 Obsidian 文件之间的绑定，支持后续幂等更新。
5. 第一阶段先完成 **AITodo -> Obsidian 单向导出**，双向导入另行设计。

## 3. 本期范围

### 3.1 AITodo 侧范围

- 新增 Obsidian Sync 配置能力。
- 新增任务到 Markdown 的渲染规则。
- 新增 AITodo 实体与 Obsidian 文件绑定记录。
- 新增导出服务，调用 `obsidianSync` 服务端文件 API。
- 支持任务创建、更新、删除或完成状态变化后的文件同步。
- 支持手动触发全量导出和单任务导出。

### 3.2 obsidianSync 依赖范围

AITodo 依赖 `obsidianSync` 增加：

- 当前文件快照 API。
- 按 path 读取文件 API。
- 按 path 写入文件 API。
- 按 path 删除文件 API。
- 写入响应返回 `fileId/path/version/contentHash/checkpoint/op`。

### 3.3 非范围

- 不在本期实现 Obsidian 本地 Markdown 修改自动回写 AITodo 数据库。
- 不让 AITodo 直连或直写 `obsidianSync` PostgreSQL。
- 不把 AITodo 关系模型完整塞进 Obsidian Sync 元数据表。
- 不做实时协同、CRDT、WebSocket 推送。
- 不把 Obsidian 文件作为 AITodo 唯一事实源；第一阶段 AITodo 仍是任务业务事实源。

## 4. 核心用户场景

1. 用户在 AITodo 创建任务，本地 Obsidian 同步后出现 `AI-Todo/<记录类型>/<日期时间>.md`。
2. 用户更新任务状态、优先级、截止时间或描述，Obsidian 对应文件同步更新。
3. 用户在 AITodo 完成任务，Obsidian 文件 front matter 和正文同步反映完成状态。
4. 用户打开 Obsidian 的 `AI-Todo/dashboards/today.md`，能看到当天建议任务摘要。
5. Agent 通过 AITodo MCP 创建任务后，最终也能在 Obsidian 中看到结构化任务文件。

## 5. 文件组织约定

所有 AITodo 生成文件必须放在固定前缀下：

```text
AI-Todo/
├── index.md
├── tasks/
│   └── <task_id>.md
├── comments/
│   └── <task_id>.md
└── dashboards/
    ├── today.md
    ├── overdue.md
    └── ready-to-start.md
```

路径规则：

1. `task_id` 使用 AITodo UUID 原文。
2. 文件扩展名统一为 `.md`。
3. 不允许 AITodo 写入 `AI-Todo/` 以外路径，除非后续配置显式允许。
4. 路径必须使用 `/`，不使用平台相关分隔符。
5. 文件名只包含 UUID、英文、数字、连字符和下划线。

## 6. 任务 Markdown 格式

单个任务文件建议格式：

```md
---
source: ai-todo
aitodo_id: 550e8400-e29b-41d4-a716-446655440000
status: todo
priority: 3
due_at:
parent_id:
tags:
  - work
updated_at: 2026-04-15T14:30:00+08:00
exported_at: 2026-04-15T14:31:00+08:00
---

# 任务标题

任务描述内容。

## 元信息

- 状态：todo
- 优先级：3
- 截止时间：未设置

## 子任务

- [ ] 子任务 A
- [ ] 子任务 B

## 依赖

- [[AI-Todo/<记录类型>/<dependency_task_id>]]

## 时间线

- 2026-04-15 14:30 创建任务
```

规则：

1. front matter 是机器可读区域，正文是用户可读区域。
2. `source: ai-todo` 用于识别由 AITodo 管理。
3. `aitodo_id` 必须存在。
4. `updated_at` 取 AITodo 任务更新时间。
5. `exported_at` 取本次导出时间。
6. 评论和系统事件可以先进入正文 `时间线`，后续再拆到 `comments/`。

## 7. AITodo 侧数据模型需求

建议新增绑定表，例如 `obsidian_file_bindings`：

| 字段 | 说明 |
| --- | --- |
| `id` | 绑定记录 UUID |
| `entity_type` | `task` / `comment` / `dashboard` |
| `entity_id` | AITodo 实体 UUID 或稳定 key |
| `vault_id` | Obsidian Sync Vault ID |
| `path` | Vault 内相对路径 |
| `file_id` | `obsidianSync` 的逻辑文件 ID |
| `version` | 当前服务端文件版本 |
| `content_hash` | 最近一次导出的内容 hash |
| `last_exported_at` | 最近导出时间 |
| `last_imported_at` | 预留，双向导入使用 |
| `meta_data` | 预留扩展 |
| `created_at` / `updated_at` | 审计字段 |

建议新增同步状态表，例如 `obsidian_sync_connections`：

| 字段 | 说明 |
| --- | --- |
| `id` | 连接记录 UUID |
| `base_url` | Obsidian Sync API Base URL |
| `vault_id` | 目标 Vault |
| `device_id` | AITodo 作为设备登录后的 ID |
| `device_name` | 建议 `AI-TODO-SERVER` |
| `refresh_token` | 加密保存 |
| `access_token_expires_at` | access token 过期时间 |
| `last_checkpoint` | 最近确认的同步 checkpoint |
| `status` | `active` / `disabled` / `error` |
| `last_error` | 最近错误摘要 |
| `created_at` / `updated_at` | 审计字段 |

## 8. 服务模块需求

建议新增：

- `ObsidianSyncClient`：封装 `obsidianSync` HTTP API、登录、刷新 token、文件读写。
- `ObsidianExportRenderer`：将任务、评论、dashboard 渲染为 Markdown。
- `ObsidianExportService`：编排导出、绑定更新、错误处理。
- 可选后台任务：定时全量校验或重试失败导出。

## 9. 同步流程

### 9.1 首次连接

1. 管理员配置 `base_url`、账号、密码、目标 Vault。
2. AITodo 以设备名 `AI-TODO-SERVER` 登录。
3. AITodo 获取 Vault 列表并绑定目标 Vault。
4. AITodo 调用 `GET /files?prefix=AI-Todo/` 读取现有投影。
5. AITodo 生成或修复本地绑定表。

### 9.2 新建或更新任务

1. AITodo 读取任务和上下文。
2. 渲染 Markdown。
3. 根据绑定表判断目标 path 和 baseVersion。
4. 调用 `PUT /files/by-path/{path}`。
5. 根据响应更新 `file_id/version/content_hash/checkpoint`。

### 9.3 删除任务或停止投影

1. AITodo 根据绑定表找到 path。
2. 调用 `DELETE /files/by-path/{path}`。
3. 根据响应更新绑定状态或删除绑定。

### 9.4 全量导出

1. 按分页读取 AITodo 任务。
2. 对每个任务计算目标 Markdown 和 hash。
3. 与绑定表和远端文件快照对比。
4. 仅写入缺失或内容变化的文件。
5. 输出导出报告。

## 10. 冲突与幂等

1. AITodo 每次写入都必须传 `idempotencyKey`。
2. 更新已有文件时应传 `baseVersion`。
3. 如果 `obsidianSync` 返回 `VERSION_CONFLICT`，第一阶段不自动覆盖：
   - 记录失败状态。
   - 拉取远端文件元数据。
   - 等待手动或后续策略处理。
4. 如果 AITodo 是单向事实源，后续可支持 `overwrite` 策略，但必须显式配置。
5. 重试同一写入不得产生重复文件。

## 11. 安全需求

1. Obsidian Sync 凭据不得写入日志。
2. refresh token 必须加密保存或由部署密钥系统管理。
3. 导出服务日志只记录 path、entity_id、状态和错误码，不记录完整 token、预签名 URL 或文件正文。
4. AITodo API 侧触发导出必须继续使用现有 API Key 鉴权。
5. 生产环境必须使用 HTTPS 的 Obsidian Sync Base URL。

## 12. 验收标准

1. 创建 AITodo 任务后，Obsidian Vault 中出现对应 Markdown。
2. 更新任务后，对应 Obsidian 文件 version 增加，内容更新。
3. 删除任务或关闭投影后，Obsidian 文件按设计删除或标记。
4. 全量导出可重复执行，重复执行不产生重复文件。
5. `obsidian_file_bindings` 能正确记录 `file_id/version/content_hash`。
6. `obsidianSync` 本地插件能拉取并落地 AITodo 写入的文件。
7. token 刷新、接口错误、版本冲突都有可观测失败记录。
8. 全量测试通过：`python -m compileall app main.py mcp_server.py`、`pytest -q`。

## 13. 后续扩展

1. 双向导入：解析 Obsidian 修改后的 Markdown 回写 AITodo。
2. 冲突 UI：展示 AITodo 版本和 Obsidian 版本差异。
3. 多 Vault：不同项目导出到不同 Vault 或不同前缀。
4. Dashboard 自动生成：按工作台视图导出每日摘要。
