AI Skill 集成指南
=================

本指南介绍如何将 `ai-todo-manager` Skill 安装到各类 AI 工具中，  
让 AI 具备自动调用 todoServer 的长效任务记忆能力。

---

目录
----

- Skill 是什么
- 支持的 AI 平台
- 安装方式
  - Cursor
  - Claude Code
  - OpenClaw
  - Nanobot
  - Codex（OpenAI）
- System Prompt 配置
- 工作流说明
- 常见问题

---

Skill 是什么
------------

`ai-todo-manager` 是一份 AI Agent Skill（行为指导文件），它告诉 AI：

- **何时** 应该调用 todoServer（布置任务、查询进度、完成阶段目标……）
- **如何** 调用（MCP Tool 还是 REST API，参数格式是什么）
- **出错时** 如何自动恢复（错误码 → 处理策略）

Skill 本身不含可执行代码，只是一份 Markdown 指导文件。AI 在会话中读取后，
会将其纳入上下文，从而主动、正确地使用 todoServer。

---

支持的 AI 平台
--------------

| 平台 | 接入协议 | Skill 目录 |
|------|---------|-----------|
| Cursor | MCP stdio | `~/.cursor/skills/` |
| Claude Code | MCP stdio | `~/.claude/skills/` |
| OpenClaw | REST API | 工具配置文件（见下文） |
| Nanobot | REST API | 工具配置文件（见下文） |
| Codex（OpenAI） | REST API | System Prompt 内嵌 |

---

安装方式
--------

### Cursor

Cursor 从 `~/.cursor/skills/` 目录自动加载个人 Skill。

**步骤 1：复制 Skill 文件**

```bash
# 从本项目复制（推荐，保持与服务端同步）
cp -r skill ~/.cursor/skills/ai-todo-manager

# 或直接创建目录并手动复制 SKILL.md / tools-reference.md
mkdir -p ~/.cursor/skills/ai-todo-manager
cp skill/SKILL.md skill/tools-reference.md ~/.cursor/skills/ai-todo-manager/
```

**步骤 2：配置 MCP Server**

在 Cursor 设置（`Settings → MCP`）或 `~/.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "ai-todo": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/absolute/path/to/todoServer",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:password@localhost:5432/todo_db",
        "API_KEY": "your-api-key"
      }
    }
  }
}
```

> 也可以不传 `env`，而是在 `todoServer` 目录下保留 `.env` 文件，
> MCP Server 启动时会自动读取。

**步骤 3：重启 Cursor**，在聊天中提到任何任务相关词语，Skill 将自动激活。

---

### Claude Code

Claude Code 从 `~/.claude/skills/` 目录自动加载 Skill，格式与 Cursor 完全相同。

```bash
# 从本项目复制
cp -r skill ~/.claude/skills/ai-todo-manager

# 或从已安装的 Cursor Skill 同步
cp -r ~/.cursor/skills/ai-todo-manager ~/.claude/skills/
```

**MCP 配置**（`~/.claude/settings.json` 中的 `mcpServers` 字段）：

```json
{
  "mcpServers": {
    "ai-todo": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/absolute/path/to/todoServer"
    }
  }
}
```

---

### OpenClaw

OpenClaw 通过 REST API 调用 todoServer，需要在工具配置文件中注册以下四个工具。

**前提**：todoServer 已启动并可访问（本地默认 `http://localhost:8000`）。

**工具配置（tools.yaml 或等效格式）**：

```yaml
tools:
  - name: upsert_task
    description: >
      当用户提到新的任务、修改任务或改变进度时调用。
      不提供 id 时为新建，提供 id 时为更新已有任务。
    method: POST
    url: http://localhost:8000/api/v1/tasks
    headers:
      Authorization: "Bearer ${AI_TODO_API_KEY}"
      Content-Type: application/json
    body_schema:
      type: object
      properties:
        title:
          type: string
          description: 任务标题（新建时必填）
        id:
          type: string
          description: 任务 UUID，提供时为更新模式
        status:
          type: string
          enum: [todo, in_progress, done, blocked]
        priority:
          type: integer
          minimum: 1
          maximum: 5
          description: 优先级，1 最高，5 最低
        due_at:
          type: string
          description: ISO 8601 格式截止时间，如 2025-12-31T23:59:59Z
        parent_id:
          type: string
          description: 父任务 UUID
        tags:
          type: array
          items:
            type: string
        meta_data:
          type: object
        thinking_process:
          type: string
          description: AI 对该任务的分析与理解

  - name: get_task_context
    description: >
      开始任何新任务前，或需要了解当前待办状态时调用。
      支持按状态、标签、语义进行过滤。
    method: GET
    url: http://localhost:8000/api/v1/tasks
    headers:
      Authorization: "Bearer ${AI_TODO_API_KEY}"
    params_schema:
      type: object
      properties:
        status_filter:
          type: string
          enum: [open, todo, in_progress, done, blocked, all]
          default: open
          description: open = todo + in_progress
        query:
          type: string
          description: 语义搜索关键词
        tags:
          type: array
          items:
            type: string
        top_n:
          type: integer
          default: 20
        offset:
          type: integer
          default: 0
        parent_id:
          type: string
          description: 仅返回指定父任务的子任务

  - name: delete_task
    description: >
      删除指定任务。默认情况下存在子任务时拒绝删除，
      cascade=true 可级联删除所有子任务。
    method: DELETE
    url: http://localhost:8000/api/v1/tasks/{task_id}
    headers:
      Authorization: "Bearer ${AI_TODO_API_KEY}"
    path_params:
      task_id:
        type: string
        description: 要删除的任务 UUID
    params_schema:
      type: object
      properties:
        cascade:
          type: boolean
          default: false

  - name: decompose_task
    description: >
      将一个大任务拆解为多个子任务。
      AI 识别到用户需要拆解目标时调用。
    method: POST
    url: http://localhost:8000/api/v1/tasks/{task_id}/decompose
    headers:
      Authorization: "Bearer ${AI_TODO_API_KEY}"
      Content-Type: application/json
    path_params:
      task_id:
        type: string
        description: 父任务 UUID
    body_schema:
      type: object
      required: [sub_tasks]
      properties:
        sub_tasks:
          type: array
          items:
            type: object
            required: [title]
            properties:
              title:
                type: string
              description:
                type: string
              priority:
                type: integer
              due_at:
                type: string
```

**环境变量**：在 OpenClaw 配置中设置 `AI_TODO_API_KEY` 为 `.env` 中的 `API_KEY` 值。

---

### Nanobot

Nanobot 同样通过 REST API 接入，工具格式略有不同，以下为 `nanobot.yaml` 参考配置：

```yaml
name: ai-todo-manager
version: "1.0"
description: AI 任务调度中心，提供跨会话的任务记忆能力

config:
  base_url: http://localhost:8000
  api_key: "${AI_TODO_API_KEY}"

system_prompt: |
  你拥有一个长效记忆工具 ai-todo。当用户布置任务、或你完成阶段性目标时，
  必须同步更新到该工具。在开始新任务前，先调用 get_task_context 检查是否
  有相关未完成项。

tools:
  - name: upsert_task
    description: 当用户提到新任务、修改任务或改变进度时调用。不提供 id 时为新建，提供 id 时为更新。
    request:
      method: POST
      path: /api/v1/tasks
      headers:
        Authorization: "Bearer {{config.api_key}}"
      body: "{{params}}"

  - name: get_task_context
    description: 获取当前相关的所有待办项，用于辅助 AI 决策。在开始新任务前必须调用。
    request:
      method: GET
      path: /api/v1/tasks
      headers:
        Authorization: "Bearer {{config.api_key}}"
      query: "{{params}}"

  - name: delete_task
    description: 删除指定任务。存在子任务时需先确认是否 cascade。
    request:
      method: DELETE
      path: /api/v1/tasks/{{params.task_id}}
      headers:
        Authorization: "Bearer {{config.api_key}}"
      query:
        cascade: "{{params.cascade}}"

  - name: decompose_task
    description: 将一个任务拆解为多个子任务。
    request:
      method: POST
      path: /api/v1/tasks/{{params.task_id}}/decompose
      headers:
        Authorization: "Bearer {{config.api_key}}"
      body:
        sub_tasks: "{{params.sub_tasks}}"
```

---

### Codex（OpenAI）

Codex 不支持本地 Skill 文件，但可以通过 **System Prompt** 内嵌工具描述来实现同等效果。

在调用 Codex API 时，将以下内容作为 System Prompt 的一部分：

```
你拥有以下 REST API 工具，Base URL 为 http://localhost:8000：

## 认证
所有请求需携带 Header: Authorization: Bearer <API_KEY>

## 工具列表

### upsert_task（POST /api/v1/tasks）
当用户提到任务或你要记录工作项时调用。
- 新建：传 title（必填）+ 可选字段
- 更新：传 id（必填）+ 要修改的字段
- status: todo/in_progress/done/blocked
- priority: 1(最高)~5(最低)

### get_task_context（GET /api/v1/tasks）
在开始任何任务前调用，了解当前待办。
- status_filter: open(默认)/todo/in_progress/done/blocked/all
- query: 语义搜索关键词
- top_n: 返回数量（默认20）

### delete_task（DELETE /api/v1/tasks/{id}）
- cascade=true: 级联删除子任务

### decompose_task（POST /api/v1/tasks/{id}/decompose）
- body: {"sub_tasks": [{"title": "...", "priority": 3}]}

## 行为准则
1. 开始新任务前先调用 get_task_context 检查未完成项
2. 用户布置任务后立即调用 upsert_task 记录
3. 完成阶段目标后更新状态为 done
```

---

System Prompt 配置
------------------

以下 System Prompt 适用于所有平台，强烈推荐加入 AI 配置中：

```
你拥有一个长效记忆工具 ai-todo（todoServer）。

核心规则：
1. 开始任何新任务前，先调用 get_task_context(status_filter="open") 检查是否有相关未完成项
2. 用户布置任务时，立即调用 upsert_task 记录，并设置合理的 priority 和 tags
3. 识别到复杂目标时，创建父任务后调用 decompose_task 拆解为子任务
4. 完成阶段目标后，调用 upsert_task 将对应任务状态更新为 done
5. 遇到阻塞时，将任务状态设为 blocked 并在 meta_data 中记录原因

错误处理：
- VALIDATION_ERROR → 检查参数格式后重试
- HAS_CHILDREN → 询问用户是否级联删除
- PARENT_NOT_DONE → 查询并列出未完成子任务
- MAX_DEPTH_EXCEEDED → 将子任务平铺到合法层级
- RATE_LIMITED → 等待 1 秒后重试
```

---

工作流说明
----------

### 场景 1：用户布置新任务

```
用户: "帮我重构登录模块"

AI 执行：
① get_task_context(query="登录模块")       # 检查是否已有相关任务
② upsert_task(title="重构登录模块",         # 创建父任务
              status="in_progress",
              tags=["backend", "refactor"])
③ decompose_task(task_id, sub_tasks=[       # 拆解为子任务
     {title: "分析现有代码", priority: 1},
     {title: "设计新接口", priority: 2},
     {title: "编写测试", priority: 3}
   ])
④ 开始执行第一个子任务...
```

### 场景 2：会话开始时主动巡检

```
AI 在每次对话开始时执行：
get_task_context(status_filter="open", top_n=10)
→ 向用户汇报：有 3 个未完成任务，最高优先级是「重构登录模块」
```

### 场景 3：完成阶段目标

```
AI 完成一个子任务后：
① upsert_task(id=<子任务id>, status="done")
② get_task_context(parent_id=<父任务id>)   # 检查所有子任务
③ 若全部完成 → upsert_task(id=<父任务id>, status="done")
```

---

常见问题
--------

**Q：MCP Server 启动失败怎么办？**

检查以下项目：
1. `todoServer/.env` 中 `DATABASE_URL` 和 `API_KEY` 是否已填写
2. PostgreSQL 是否已启动（或 Docker 容器是否运行）
3. 虚拟环境是否已激活（`source .venv/bin/activate`）
4. 依赖是否已安装（`pip install -r requirements.txt`）

```bash
# 手动测试 MCP Server 是否正常
cd /path/to/todoServer
source .venv/bin/activate
python mcp_server.py  # 正常时会等待 stdin 输入，无报错即可
```

**Q：语义搜索（query 参数）不生效？**

`EMBEDDING_API_KEY` 未配置时，系统自动降级为关键词搜索（仍然可用，只是不支持语义相似度）。  
配置 OpenAI 或兼容 API 的 key 后重启服务即可启用语义搜索。

**Q：OpenClaw / Nanobot 调用返回 401？**

检查请求 Header 中 `Authorization: Bearer <API_KEY>` 的 `<API_KEY>` 是否与 `.env` 中的 `API_KEY` 一致。

**Q：如何在多台机器或团队中共享同一个 todoServer？**

修改工具配置中的 `base_url` 为服务器的公网地址即可，认证机制不变。  
建议在服务器上通过 `docker compose up -d` 运行，并通过反向代理（如 Nginx）暴露 HTTPS 接口。

---

参考资料
--------

- Skill 源文件：`~/.cursor/skills/ai-todo-manager/SKILL.md`（Cursor）
- Skill 源文件：`~/.claude/skills/ai-todo-manager/SKILL.md`（Claude Code）
- REST API 完整文档：[API.md](API.md)
- 架构与开发指南：[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
- 产品与系统设计：[需求文档.md](需求文档.md)
