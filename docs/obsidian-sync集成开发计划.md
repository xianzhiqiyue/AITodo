---
title: AITodo 与 Obsidian Sync 集成开发计划
type: plan
status: active
owner: TBD
created: 2026-04-15
updated: 2026-04-15
related_docs:
  - SOP.md
  - obsidian-sync集成需求文档.md
  - ../../obsidianSync/docs/AITodo接入服务端文件API设计.md
tags:
  - aitodo
  - obsidian-sync
  - plan
---

# AITodo 与 Obsidian Sync 集成开发计划

## 1. 本次交付目标

先完成文档、协议和边界收敛，再进入代码实现。整体分两仓推进：

1. `obsidianSync`：先提供服务端文件 API，保证外部系统可按 path 安全读写 Vault 文件。
2. `AITodo`：再接入这些 API，把任务导出为 `AI-Todo/` 下的 Markdown 文件。

## 2. 阶段拆解

| 阶段 | 仓库 | 目标 | 完成标准 |
| --- | --- | --- | --- |
| P0 文档冻结 | 两仓 | 需求、API、计划、验收标准明确 | 文档更新完成并通过格式检查 |
| P1 文件 API | obsidianSync | 实现 files snapshot / read / write / delete | API 回归测试通过 |
| P2 AITodo 绑定模型 | AITodo | 增加连接表和文件绑定表 | Alembic 迁移和模型测试通过 |
| P3 AITodo 导出服务 | AITodo | 渲染 Markdown 并调用 obsidianSync API | 单任务导出测试通过 |
| P4 闭环验证 | 两仓 | AITodo 任务同步到本地 Obsidian | 冒烟和手工验证通过 |

## 3. obsidianSync 先行任务

1. 新增或扩展服务端文件路由：
   - `GET /vaults/:vaultId/files`
   - `GET /vaults/:vaultId/files/by-path/*`
   - `PUT /vaults/:vaultId/files/by-path/*`
   - `DELETE /vaults/:vaultId/files/by-path/*`
2. 抽取可复用写入事务，避免复制 `sync/commit` 大段逻辑。
3. 补充 API 测试：
   - create by path
   - update by path
   - delete by path
   - idempotency replay
   - version conflict
   - prefix snapshot
4. 运行：
   - `npm run typecheck`
   - `npm test`
   - `scripts/regression-sync-api.sh`

## 4. AITodo 后续任务

1. 新增配置和数据模型：
   - `obsidian_sync_connections`
   - `obsidian_file_bindings`
2. 新增服务：
   - `ObsidianSyncClient`
   - `ObsidianExportRenderer`
   - `ObsidianExportService`
3. 新增 API / MCP：
   - 手动连接测试
   - 单任务导出
   - 全量导出
   - 查询导出状态
4. 补充测试：
   - Markdown 渲染 snapshot 或结构断言
   - client HTTP mock
   - service 绑定更新
   - API 权限和错误处理
5. 运行：
   - `python -m compileall app main.py mcp_server.py`
   - `pytest -q`

## 5. 数据与权限约束

1. AITodo 不直接写 `obsidianSync` 数据库或对象桶。
2. AITodo refresh token 必须加密或由部署环境托管。
3. AITodo 生成文件默认只写 `AI-Todo/` 前缀。
4. 双向导入不在本阶段实现。
5. 版本冲突默认记录失败，不自动覆盖用户侧修改。

## 6. 验收清单

- [ ] `obsidianSync` API 能按 path 创建文件，并返回 `fileId/version/contentHash/checkpoint`。
- [ ] `obsidianSync` API 能按 prefix 返回当前文件快照。
- [ ] `obsidianSync` 写入后的文件能被现有插件 `pull` 到本地。
- [ ] AITodo 能渲染任务 Markdown。
- [ ] AITodo 能保存 `task_id -> fileId/path/version/contentHash`。
- [ ] AITodo 重复导出不会重复创建文件。
- [ ] 两仓测试命令均通过。

## 7. 风险与取舍

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 直接写文件 API 与原同步协议逻辑分叉 | 数据一致性风险 | 抽取共享事务服务，测试覆盖 change_events/checkpoint |
| AITodo 和 Obsidian 同时编辑同一文件 | 版本冲突 | 第一阶段默认不自动覆盖，记录失败 |
| token 泄露 | 安全风险 | 不打印 token/URL，refresh token 加密保存 |
| 大量任务全量导出 | 性能压力 | 分页、hash 对比、只写变化文件 |
