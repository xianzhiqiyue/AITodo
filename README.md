AI 任务调度中心（todoServer）
================================

一个 **AI 优先（AI-first）** 的任务调度中心，为大模型提供持久化的「任务记忆」与结构化任务管理能力。  
它既可以作为普通 Todo 服务使用，也可以作为 MCP / Tool 后端，被 Cursor、Claude、Nanobot/OpenClaw 等调用。

---

目录
----

- 项目特性
- 快速开始
  - 本地运行（Python）
  - Docker 一键启动
- 配置说明（`.env`）
- REST API 概览
- MCP 集成示例（以 Cursor 为例）
- AI Skill 集成
- 运行测试
- 目录结构

---

项目特性
--------

- **结构化任务管理**
  - 基本 CRUD：创建 / 更新 / 查询 / 删除任务
  - 状态流转：`todo → in_progress → done`，支持 `blocked` 挂起
  - 父子任务：支持最多 **5 级嵌套** 的父子任务树
- **AI 友好**
  - 标准化的 Task Schema（支持 `meta_data`、`thinking_process`）
  - 语义检索：基于 `pgvector` + 嵌入模型
  - MCP Server：开箱即用的 `upsert_task` / `get_task_context` / `delete_task` / `decompose_task`
- **生产可用**
  - FastAPI + PostgreSQL(+pgvector) + Alembic
  - 结构化 JSON 日志（`structlog`）
  - API Key 认证 + 简单限流中间件
  - Docker & docker-compose 一键部署

---

快速开始
--------

### 1. 本地运行（Python）

前置依赖：

- Python 3.11+
- PostgreSQL 15+，并安装 `pgvector` 扩展

#### 1.1 克隆代码并安装依赖

```bash
git clone <your-repo-url> todoServer
cd todoServer

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 1.2 配置环境变量

复制示例配置并按需修改：

```bash
cp .env.example .env
```

关键变量（至少需要配置）：

- `DATABASE_URL`：PostgreSQL 连接串（建议 asyncpg 驱动，例如 `postgresql+asyncpg://user:password@host:5432/todo_db`）
- `API_KEY`：访问 REST API 的密钥（**必填，无默认值**）
- `EMBEDDING_API_KEY`：调用嵌入模型的 key（可选，不填时自动降级为关键词搜索）

#### 1.3 初始化数据库

```bash
alembic upgrade head
```

#### 1.4 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

访问：

- Swagger UI：`http://localhost:8000/docs`
- ReDoc：`http://localhost:8000/redoc`
- 健康检查：`http://localhost:8000/health`

> **注意**：访问任何 `/api/v1/...` 接口都需要携带 `Authorization: Bearer <API_KEY>` 头。

---

### 2. Docker 一键启动

确保已安装：

- Docker
- docker-compose（或 `docker compose`）

#### 2.1 准备 `.env`

```bash
cp .env.example .env
# 编辑 .env，至少调整：
# - DATABASE_URL
# - POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD
# - API_KEY
```

#### 2.2 启动

```bash
docker compose up --build
```

这会启动两个容器：

- `ai-todo-api`：FastAPI 应用（默认对外暴露 `8000` 端口）
- `db`：PostgreSQL + pgvector

**启动流程**：

- `db` 通过 `pg_isready` 健康检查就绪
- `ai-todo-api` 启动后执行 `alembic upgrade head`
- `ai-todo-api` 通过 `/health` 健康检查就绪

---

配置说明（.env）
----------------

`.env.example` 中包含一个参考配置，关键项如下：

```env
POSTGRES_DB=todo_db
POSTGRES_USER=user
POSTGRES_PASSWORD=password
DATABASE_URL=postgresql+asyncpg://user:password@db:5432/todo_db
API_KEY=your-secure-api-key
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://api.openai.com/v1
LOG_LEVEL=INFO
```

- **API_KEY**：必须是一个足够随机的字符串，部署前务必修改。
- **EMBEDDING_API_KEY**：留空时不启用语义搜索，只做标题/标签关键词过滤。
- **LOG_LEVEL**：`DEBUG` / `INFO` / `WARNING` / `ERROR`。

---

REST API 概览
--------------

完整字段、示例、错误码等请见 [`API.md`](API.md)。这里给出一个超简版说明。

所有业务接口都在 `/api/v1` 前缀下，并且：

- **认证**：必须带 Header

  ```http
  Authorization: Bearer <API_KEY>
  Content-Type: application/json
  ```

- **错误格式**（示例）：

  ```json
  {
    "error": {
      "code": "TASK_NOT_FOUND",
      "message": "Task with id '...' does not exist."
    }
  }
  ```

### 主要端点

- `GET /health`  
  - 健康检查，不需要 API Key。

- `POST /api/v1/tasks`  
  - 创建任务，Body 为 `TaskCreate`。

- `PUT /api/v1/tasks/{id}`  
  - 更新任务，Body 为 `TaskUpdate`，只更新提供的字段。

- `GET /api/v1/tasks`  
  - 查询任务列表，支持：
    - `status_filter`: `open|todo|in_progress|done|blocked|all`
    - `tags`: 多个标签
    - `query`: 语义或关键词搜索
    - `parent_id`: 仅返回某个父任务下的子任务

- `GET /api/v1/tasks/{id}`  
  - 获取单个任务（含 children）。

- `DELETE /api/v1/tasks/{id}?cascade={bool}`  
  - 删除任务，默认禁止删除存在子任务的父任务；`cascade=true` 时连同子树一起删除。

- `POST /api/v1/tasks/{id}/decompose`  
  - 将一个大任务拆解为多个子任务。

---

MCP 集成示例（以 Cursor 为例）
------------------------------

本项目自带一个 MCP Server 入口：`mcp_server.py`。  
只要在支持 MCP 的客户端（如 Cursor、Claude Desktop）中配置即可使用。

### 1. 启动 MCP Server

在项目根目录：

```bash
source .venv/bin/activate  # 如使用虚拟环境
python mcp_server.py
```

该进程通过 **stdio** 与宿主工具通信；通常由宿主工具负责拉起，你本地不需要手动运行。

### 2. Cursor 配置示例

在 Cursor 设置中添加 MCP 配置（伪示例）：

```json
{
  "mcpServers": {
    "ai-todo": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/abs/path/to/todoServer"
    }
  }
}
```

注册的 MCP Tools：

- `upsert_task`：创建/更新任务
- `get_task_context`：按状态/标签/语义获取任务列表
- `delete_task`：删除任务，支持 `cascade`
- `decompose_task`：将一个任务拆分为多个子任务

调用参数与语义，见主需求文档《`需求文档.md`》第 2.3 节。

---

AI Skill 集成
-------------

本项目附带一份 **AI Agent Skill**（`ai-todo-manager`），让 Cursor、Claude Code、OpenClaw、Nanobot、Codex 等 AI 工具在执行任务时，能自动感知并调用 todoServer，实现跨会话的任务记忆。

### Skill 能做什么

- 用户布置任务时，**自动创建 / 更新**对应的 todo 记录
- 每次开始工作前，**主动巡检**未完成任务
- 识别可拆解的目标时，自动调用 `decompose_task`
- 阶段完成后，同步标记任务状态为 `done`

### 一键安装

```bash
# Cursor（所有项目均可用）
cp -r ~/.cursor/skills/ai-todo-manager ~/.cursor/skills/   # 若尚未存在

# Claude Code（所有项目均可用）
cp -r skill/ ~/.claude/skills/ai-todo-manager/
```

> 详细的多平台安装步骤（OpenClaw / Nanobot / Codex 配置示例）请参考 [`SKILL_GUIDE.md`](SKILL_GUIDE.md)。

### System Prompt 推荐

在任意 AI 工具的系统提示中加入以下内容，可显著提升任务跟踪的主动性：

```
你拥有一个长效记忆工具 ai-todo。当用户布置任务、或你完成阶段性目标时，
必须同步更新到该工具。在开始新任务前，先调用 get_task_context 检查是否
有相关未完成项。
```

---

运行测试
--------

项目包含 **34 个自动化测试**（服务层 + API 层），推荐在改动后运行：

```bash
source .venv/bin/activate
pytest tests/ -v
```

测试覆盖内容包括：

- 基本 CRUD 与状态流转
- 父子任务规则（最大 5 层、删除保护）
- 循环父子关系防护（自引用/后代引用）
- 语义检索降级逻辑
- API Key 认证与限流中间件

---

目录结构
--------

```text
todoServer/
├── main.py                 # FastAPI 入口
├── mcp_server.py           # MCP Server 入口
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── API.md
├── DEVELOPER_GUIDE.md
├── SKILL_GUIDE.md          # AI Skill 安装与配置指南
├── 需求文档.md             # 产品 & 系统设计文档
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial.py
├── app/
│   ├── config.py           # 配置（pydantic-settings）
│   ├── database.py         # 异步数据库引擎 & Session
│   ├── models.py           # ORM 模型（含 pgvector/JSON 兼容类型）
│   ├── schemas.py          # Pydantic 请求/响应模型
│   ├── errors.py           # 统一错误码 & 异常
│   ├── logging.py          # structlog JSON 日志
│   ├── services/
│   │   ├── task_service.py # 核心业务逻辑
│   │   └── embedding_service.py
│   └── api/
│       ├── routes.py       # REST 路由
│       ├── deps.py         # 依赖注入（认证、TaskService 等）
│       └── middleware.py   # 限流 & 请求日志中间件
└── tests/
    ├── conftest.py
    ├── test_task_service.py
    └── test_api.py
```

如需深入理解架构与扩展方式，请参考 [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md)。

