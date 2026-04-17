---
title: AITodo SOP
type: sop
status: active
owner: TBD
created: 2026-04-15
updated: 2026-04-15
related_docs:
  - README.md
  - SKILL.md
  - docs/开发规范.md
  - docs/迁移规范.md
  - docs/运维与排障.md
  - docs/v1.2-需求文档.md
  - docs/v1.2-架构设计文档.md
  - docs/v1.2-模块设计文档.md
  - docs/v1.2-开发计划.md
tags:
  - sop
  - aitodo
  - development-process
  - documentation
  - local-service
  - operations
  - obsidian-sync-integration
---

# AITodo SOP

> 统一 SOP 文件。本文参考 `oneID/SOP.md` 的“根目录唯一 SOP + 文档先行 + 开发验证闭环”方式，结合 AITodo 当前 FastAPI / MCP / PostgreSQL / pgvector 后端形态制定。
> 适用范围：需求、调研、设计、开发、测试、迁移、运维、本地服务启停、发布语义，以及后续与 `obsidianSync` 的服务端集成。

---

## A. 开发与文档治理 SOP

> 状态：生效
> 生效日期：2026-04-15
> 核心原则：先收敛事实和范围，再计划，再开发，再验证，再沉淀。

---

## 1. 当前项目结构结论

AITodo 是一个面向 AI Agent 的任务中心后端，当前事实入口以根目录 `README.md`、`SKILL.md` 和 `docs/` 下的需求 / 架构 / 模块 / 迁移 / 运维文档为主。

```text
AITodo/
├── app/                # FastAPI 应用代码、模型、服务、API 路由
│   ├── api/            # REST API、鉴权依赖、中间件
│   └── services/       # 任务、拆解、提醒、通知、工作台等业务服务
├── alembic/            # 数据库迁移
├── tests/              # pytest 测试
├── docs/               # 正式文档，当前采用中文主题文档命名
├── main.py             # FastAPI 入口
├── mcp_server.py       # MCP stdio 服务入口
├── README.md           # 仓库总入口
├── SKILL.md            # Agent 可调用能力说明
└── SOP.md              # 统一 SOP
```

当前文档主线：

- 需求：`docs/v1.2-需求文档.md`
- 架构：`docs/v1.2-架构设计文档.md`
- 模块：`docs/v1.2-模块设计文档.md`、`docs/下一阶段模块设计与开发文档.md`
- 计划：`docs/v1.2-开发计划.md`、`docs/规划与开发计划.md`
- 迁移：`docs/迁移规范.md`
- 运维：`docs/运维与排障.md`
- 开发规范：`docs/开发规范.md`
- 归档：`docs/归档索引.md`

后续如新增 `docs/requirements/`、`docs/plans/`、`docs/tests/`、`docs/summary/` 等细分目录，必须先更新 `README.md`、本 SOP 和 `docs/归档索引.md`，避免同一事实源分散。

## 2. 总原则

1. **中文优先**：文档正文、说明性注释、任务总结默认使用中文；API 字段、协议名、错误码、库名保留原文。
2. **文档先行**：新功能、跨服务集成、迁移和发布必须先有需求 / 设计 / 计划或在现有文档中补齐章节。
3. **范围先行**：范围变化优先回写需求或模块设计，不只在代码、计划或聊天记录里改变范围。
4. **最小可逆变更**：优先复用已有模型、服务、路由和测试模式；不顺手重构，不引入未批准新依赖。
5. **数据库可迁移**：模型变化必须配套 Alembic 迁移、迁移测试和回滚/降级说明。
6. **API 兼容优先**：已公开 REST / MCP 入参出参不破坏；破坏性变更必须明确版本策略和迁移路径。
7. **验证后声明完成**：完成说明必须包含真实执行过的测试、类型/编译检查或手工验证证据。
8. **跨仓库不直写数据库**：与 `obsidianSync` 集成时，AITodo 默认通过对方公开 API 写入 Vault 文件，不直接修改对方 PostgreSQL 或 MinIO/S3 数据。

---

## 3. 任务类型与必备材料

| 任务类型 | 触发场景 | 必备材料 | 完成标准 |
| --- | --- | --- | --- |
| 需求 / 范围 | 新能力、行为变化、跨服务集成 | 更新 `docs/v1.2-需求文档.md` 或新增明确主题文档 | 背景、目标、范围、不做项、验收标准清楚 |
| 架构 / 模块设计 | 数据模型、服务边界、同步协议、AI 流程 | 更新架构 / 模块设计文档 | 说明对象、接口、数据流、失败处理和风险 |
| 开发实现 | REST、MCP、服务、模型、迁移、脚本 | 关联需求或计划；小任务可在最终说明中记录 | 代码实现、迁移和测试均通过 |
| 数据库迁移 | 新表、字段、索引、约束、向量能力 | Alembic migration + 迁移说明 | `alembic upgrade head` 和相关测试通过 |
| 测试 / 验收 | 功能完成、缺陷修复、发布前检查 | pytest 或验收清单 | 有实际结果、失败项和未覆盖风险 |
| 运维 / 发布 | 启停、部署、环境变量、故障处理 | 更新 `docs/运维与排障.md` 或发布说明 | 明确命令、环境、回滚和健康检查 |
| 复盘 / 总结 | 阶段完成、问题关闭、方案落地 | 更新归档索引或新增总结文档 | 说明完成项、遗留风险和下一步 |

---

## 4. 标准开发流程

### 4.1 Step 0：任务分流

收到任务后先判断类型：

1. **只调研 / 只设计**：先补文档，不改代码。
2. **小缺陷修复**：定位影响范围，补最小回归测试后修复。
3. **模型 / 迁移变化**：先确认迁移策略，再改模型和 Alembic。
4. **REST / MCP 能力变化**：先确认接口兼容性，再实现并补测试。
5. **跨仓库集成**：先写清 API 边界、凭据边界、失败重试和幂等策略。

如果任务范围不清楚，优先补“待确认问题”；不要直接扩大实现范围。

### 4.2 Step 1：需求和设计输入

需求文档至少包含：

1. 背景与目标
2. 本期范围
3. 明确不做
4. 数据对象和字段
5. API / MCP / 后台任务影响
6. 失败场景与权限边界
7. 验收标准

涉及 `obsidianSync` 的集成需求，必须额外写清：

- AITodo 数据如何映射为 Obsidian Markdown 文件。
- 是否单向导出还是双向导入。
- `task_id` 与 Obsidian `fileId/path/version/contentHash` 的绑定方式。
- 冲突策略：AITodo 为准、Obsidian 可编辑、或人工冲突处理。
- 不直接写 `obsidianSync` 数据库的理由和例外审批条件。

### 4.3 Step 2：计划拆解

开发计划至少包含：

1. 关联文档
2. 交付目标
3. 数据模型 / API / MCP / 服务 / 脚本影响范围
4. 任务拆解和顺序
5. 测试策略
6. 风险与不做项

小修可不新增计划文件，但最终说明必须写清验证结果。

### 4.4 Step 3：实现

实现时遵守：

1. 先看现有 `app/services/` 和 `app/api/routes.py` 的模式。
2. 数据库字段新增必须同步 `app/models.py`、Pydantic schema、服务层和 Alembic migration。
3. REST 入参出参变化必须补测试。
4. MCP 工具变化必须同步 `mcp_server.py` 和 `SKILL.md`。
5. 不在业务服务中硬编码密钥、服务地址或用户凭据。
6. 不把生产凭据写入 `.env.example`、文档或测试 fixture。

### 4.5 Step 4：测试与验证

默认验证命令：

```bash
python -m compileall app main.py mcp_server.py
pytest -q
```

数据库迁移相关任务还必须运行：

```bash
python -m alembic upgrade head
```

如使用 SQLite 本地兜底，应明确说明它只验证通用逻辑，不代表 PostgreSQL + pgvector 生产能力完全通过。

### 4.6 Step 5：总结与归档

任务完成后，最终说明至少包含：

1. 修改了哪些文件
2. 完成了哪些能力或规则
3. 执行了哪些验证
4. 未覆盖风险
5. 后续建议

阶段性主题完成后，必要时更新 `docs/归档索引.md` 或新增总结文档。

---

## B. 本地服务与发布语义 SOP

## 5. 本地环境变量

当前本地开发默认使用根目录 `.env`：

```bash
cp .env.example .env
```

规则：

1. `.env` 是本机私有配置，禁止提交真实密钥。
2. `.env.example` 只保留模板、开发默认值和变量说明。
3. 新增变量必须同步更新 `.env.example`、`README.md` 和必要的运维文档。
4. 生产环境由容器、部署平台或密钥管理系统注入，不复用本机 `.env`。

## 6. 本地启动语义

本地 API：

```bash
pip install -r requirements.txt
docker compose up -d db
python -m alembic upgrade head
uvicorn main:app --reload
```

SQLite 快速验证：

```bash
export DATABASE_URL=sqlite+aiosqlite:///./aitodo.db
python -m alembic upgrade head
uvicorn main:app --reload
```

Docker 一体启动：

```bash
docker compose up --build
```

MCP stdio：

```bash
python mcp_server.py
```

语义边界：

- “本地启动 / 重启”只影响本机服务，不等同发布。
- “迁移”必须说明目标数据库和是否可回滚。
- “发布 / 上线 / 部署到服务器”必须先有验证记录、目标环境和回滚方案。

---

## C. `obsidianSync` 集成专项规矩

AITodo 与 `obsidianSync` 打通时，默认采用长期路线：先增强 `obsidianSync` 的服务端 API，再由 AITodo 调用这些 API，把任务数据写成 Obsidian Vault 中的 Markdown 文件。

### 7. 集成边界

1. AITodo 是业务事实源；Obsidian 文件是用户可读、可同步、可检索的投影。
2. 写入 Obsidian Vault 必须走 `obsidianSync` API，不直接写对方 PostgreSQL 表或对象桶。
3. AITodo 侧必须保存任务与 Obsidian 文件绑定关系。
4. 第一阶段默认 **AITodo -> Obsidian 单向导出**；双向导入必须另行设计冲突策略。
5. Obsidian 文件路径统一收敛在 `AI-Todo/` 前缀下，避免污染用户 Vault 根目录。

### 8. 推荐文件映射

```text
AI-Todo/
├── index.md
├── tasks/
│   └── <task_id>.md
├── dashboards/
│   ├── today.md
│   ├── overdue.md
│   └── ready-to-start.md
└── comments/
    └── <task_id>.md
```

任务 Markdown 必须包含 front matter：

```yaml
---
source: ai-todo
aitodo_id: <uuid>
status: todo
priority: 3
due_at:
tags: []
updated_at: <iso8601>
---
```

### 9. AITodo 侧绑定信息

后续实现时，应在 AITodo 侧持久化以下最小绑定信息：

- `entity_type`：`task` / `comment` / `dashboard`
- `entity_id`：AITodo 实体 ID
- `vault_id`
- `path`
- `file_id`
- `version`
- `content_hash`
- `last_exported_at`
- `last_imported_at`

### 10. 验收标准

集成能力完成前必须证明：

1. AITodo 创建任务后，本地 Obsidian 能同步看到对应 Markdown。
2. AITodo 更新任务后，Obsidian 文件版本随同步更新。
3. 删除 / 完成 / 改期等关键状态有明确文件表达。
4. 重试不会重复创建文件。
5. `obsidianSync` 健康检查、迁移、回归测试通过。
6. 凭据不会出现在日志、文档、测试快照或仓库中。

---

## D. 执行检查清单

### 需求 / 计划前

- [ ] 是否先看 `README.md`、`SKILL.md`、本 SOP 和相关 `docs/` 文档？
- [ ] 是否明确任务类型、范围和不做项？
- [ ] 是否明确数据模型、API / MCP 影响和验收标准？
- [ ] 是否确认跨仓库集成边界？

### 开发 / 交付前

- [ ] 是否有需求 / 计划 / 设计依据？
- [ ] 是否没有引入未批准的新依赖？
- [ ] 是否同步更新 schema、迁移、服务和测试？
- [ ] 是否运行并记录适用验证命令？
- [ ] 是否说明未覆盖风险？

从本 SOP 生效后，后续所有 AITodo 需求、调研、开发、测试、迁移、运维和 `obsidianSync` 集成任务默认按本文执行。
