AI 任务调度中心开发者指南
========================

本文面向**维护者与贡献者**，介绍 todoServer 的架构、关键模块以及常见开发流程。

---

整体架构
--------

系统采用典型的分层架构：

```mermaid
flowchart TB
    subgraph entry [EntryPoints]
        MainPy["main.py (FastAPI)"]
        McpPy["mcp_server.py (stdio MCP)"]
    end
    subgraph api [APILayer]
        Routes["app/api/routes.py"]
        Deps["app/api/deps.py (Auth/DI)"]
        MW["app/api/middleware.py (RateLimit/Log)"]
    end
    subgraph services [ServiceLayer]
        TS["TaskService"]
        ES["EmbeddingService"]
    end
    subgraph data [DataLayer]
        Models["app/models.py (ORM)"]
        DB[(PostgreSQL + pgvector)]
    end
    MainPy --> MW --> Routes
    Routes --> Deps
    Routes --> TS
    McpPy --> TS
    TS --> ES
    TS --> Models --> DB
    ES --> DB
```

**层次划分：**

- **Entry 层**
  - `main.py`：HTTP 入口（FastAPI）
  - `mcp_server.py`：MCP 入口（stdio）
- **API 层**
  - `routes.py`：声明 REST 路由与 request/response 模型
  - `deps.py`：依赖注入（认证、TaskService 实例等）
  - `middleware.py`：限流与请求日志中间件
- **Service 层**
  - `TaskService`：所有业务规则（状态流转、父子任务、语义检索等）
  - `EmbeddingService`：嵌入向量生成（可降级）
- **Data 层**
  - `models.py`：SQLAlchemy ORM 模型（含 PG/SQLite 兼容类型）
  - `database.py`：异步 Engine + Session 工厂
  - `alembic/`：迁移脚本（PostgreSQL 生产环境专用）

---

关键模块说明
------------

### 配置（app/config.py）

使用 `pydantic-settings` 管理配置：

- `database_url`：默认 `postgresql+asyncpg://user:password@localhost:5432/todo_db`
- `api_key`：**必填**，无默认值（防止易猜测凭据）
- `embedding_api_key`：可选，留空则禁用语义搜索
- `embedding_base_url`：默认 `https://api.openai.com/v1`
- `log_level`：`INFO` / `DEBUG` / ...

通过 `get_settings()`（带 `@lru_cache`）在全局复用。

### 数据访问（app/database.py & app/models.py）

#### database.py

- `Base`：SQLAlchemy DeclarativeBase
- **惰性初始化**：
  - `_get_engine()`：首次调用时读取 `Settings.database_url` 创建 `AsyncEngine`
  - `get_session_factory()`：创建全局 `async_sessionmaker`
  - `get_async_session()`：FastAPI 依赖，用 `async with` 生成 `AsyncSession`

这样可以避免在导入阶段就强绑定配置，方便测试中覆盖 `get_settings`。

#### models.py

为兼容生产 PostgreSQL 与测试 SQLite，使用自定义 TypeDecorator：

- `FlexibleUUID`：PG 上使用 `UUID(as_uuid=True)`，SQLite 上使用 `String(36)`
- `StringList`：PG 上是 `ARRAY(Text)`，SQLite 上是 `TEXT(JSON)`，内部序列化为 JSON 数组
- `FlexibleJSON`：PG 上是 `JSONB`，SQLite 上是 `TEXT(JSON)`
- `OptionalVector(dim)`：PG 上是 `pgvector.Vector(dim)`，SQLite 上是 `TEXT(JSON)`

`Task` 模型大致对应需求文档 2.2 的表结构：

- `id`、`title`、`description`、`status`、`priority`、`due_at`
- `parent_id`：自引用 FK，配合 `children` / `parent` 关系
- `tags`：`StringList`
- `meta_data`：`FlexibleJSON`
- `embedding`：`OptionalVector(1536)`
- `created_at` / `updated_at`

关系：

- `children`: `relationship("Task", back_populates="parent", cascade="all, delete-orphan")`
- `parent`: 自引用，一侧 `remote_side=[id]`

> 生产环境 Schema 仍由 Alembic 的 PG 类型定义主导，TypeDecorator 主要为测试环境服务。

### 业务服务（app/services/task_service.py）

`TaskService` 是整个系统的核心，所有入口（HTTP/MCP）都通过它来操作任务。

构造函数：

```python
class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService | None = None,
        is_postgres: bool = True,
    ): ...
```

重要字段与常量：

- `VALID_STATUSES = {"todo", "in_progress", "done", "blocked"}`
- `VALID_STATUS_FILTERS = {"open", "todo", "in_progress", "done", "blocked", "all"}`
- `MAX_DEPTH = 5`：最大嵌套层级

#### 主要方法

- `upsert_task(data: TaskCreate | None, update_data: TaskUpdate | None, task_id: UUID | None) -> TaskResponse`
  - 内部分发为 `_create_task` 与 `_update_task`
  - 创建/更新时会根据需要调用 `_generate_embedding`
- `get_task_context(...) -> TaskListResponse`
  - 对应 REST 的列表查询和 MCP 的 `get_task_context`
  - 根据是否配置 `EmbeddingService` 决定走 `_semantic_search` 或 `_keyword_search`
- `delete_task(task_id, cascade=False) -> DeleteResponse`
  - 使用 `_count_descendants` 统计后代数；非 cascade 时阻止删除
- `decompose_task(task_id, sub_tasks) -> DecomposeResponse`
  - 创建子任务并检查最大层级限制

#### 关键业务规则

1. **状态流转校验**

   - 新状态必须在 `VALID_STATUSES` 中，否则 `400 VALIDATION_ERROR`
   - 从任意状态切到 `done` 时：
     - 若仍存在 `status != "done"` 的子任务，则抛 `PARENT_NOT_DONE`

2. **父子层级 & 循环检测**

   - `_get_depth(parent_id)`：沿父链向上查询深度；使用 `visited` 集防止环
   - 更新父节点时：
     - 如果 `parent_id == self_id` → 拒绝（自引用）
     - 使用 `_is_descendant_of(task_id, new_parent)` 检查新父是否是自己的后代，避免形成环
     - 深度 +1 大于 `MAX_DEPTH` 时抛 `MAX_DEPTH_EXCEEDED`

3. **status_filter 行为**

   - 仅允许 `open/todo/in_progress/done/blocked/all`
   - 非法值直接抛 `VALIDATION_ERROR`，不会“静默变成 all”

4. **标签过滤**

   - PostgreSQL：使用 `Task.tags.overlap(tags)`
   - SQLite：降级为 `LIKE "%tag%"` 形式的 OR 条件

5. **父任务删除**

   - 使用 `_count_descendants` 统计整棵子树节点数（含多层）
   - `cascade=false` 且存在任意后代 → 抛 `HAS_CHILDREN`
   - `cascade=true` → 依赖 SQLAlchemy 的 `delete-orphan` 级联删除，`deleted_count = 1 + descendants`

### 嵌入服务（app/services/embedding_service.py）

`EmbeddingService` 负责调用 OpenAI 兼容接口生成向量：

- 若 `embedding_api_key` 为空，直接返回 `None`（不启用语义搜索）
- 内部使用 `httpx.AsyncClient` 发送请求
- 出错时记录 warning 日志并返回 `None`

`TaskService` 中：

- 创建/更新任务时，仅在标题/描述变化时才重新生成 embedding
- `_semantic_search` 中，若生成 embedding 失败会回退到 `_keyword_search`

---

HTTP 层（FastAPI）
-----------------

### main.py

- 创建 FastAPI 应用：

  ```python
  app = FastAPI(
      title="AI 任务调度中心",
      description="AI-first task scheduling center ...",
      version="1.0.0",
      lifespan=lifespan,
  )
  ```

- `lifespan` 中调用 `setup_logging()` 配置 `structlog` JSON 日志
- 注册中间件：
  - `RequestLoggingMiddleware`
  - `RateLimitMiddleware`
- 挂载路由：
  - `app.include_router(router)`（业务路由）
  - `app.include_router(health_router)`（健康检查）
- 全局异常处理：
  - 捕获 `AppError` 并按统一错误格式返回

### 路由与依赖（app/api）

- `routes.py`：
  - 所有 `/api/v1/...` 路由都带有 `Depends(verify_api_key)`
  - 路由函数只做参数解析与调用 `TaskService`，无业务逻辑
- `deps.py`：
  - `verify_api_key`：
    - `/health` 跳过认证
    - 其它路径校验 Bearer token 是否等于 `settings.api_key`
  - `get_task_service`：
    - 基于 `get_async_session` 和 `get_settings` 构造 `TaskService`
    - 自动填充 `embedding_service` 和 `is_postgres` 标志
- `middleware.py`：
  - `RateLimitMiddleware`：滑动窗口限流 + key 数量上限 + 清理空 key
  - `RequestLoggingMiddleware`：记录基础访问日志

---

MCP Server（mcp_server.py）
---------------------------

使用 `mcp.server.fastmcp.FastMCP` 实现：

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ai-todo")
```

注册的 Tool 与 REST API 一一对应：

- `upsert_task(...)` → `TaskService.upsert_task`
- `get_task_context(...)` → `TaskService.get_task_context`
- `delete_task(...)` → `TaskService.delete_task`
- `decompose_task(...)` → `TaskService.decompose_task`

关键注意点：

- MCP 层不会做业务逻辑，只负责：
  - 将传入的字符串/列表转为 Pydantic 模型或 Python 类型
  - 调用 `TaskService`
  - 将结果 `model_dump()` 并 `json.dumps` 后返回
- `is_postgres` 标志通过读取 `Settings.database_url` 来判断，保证 MCP 调用与 HTTP 调用共享同一套行为（尤其是标签过滤逻辑）。

---

测试策略
--------

所有测试位于 `tests/` 目录，使用 `pytest + pytest-asyncio`：

- `tests/conftest.py`
  - 使用 SQLite 内存库 + 自定义 TypeDecorator 实现快速测试
  - 通过覆盖 `get_settings` / `get_async_session` 注入测试配置
  - 自动创建/清理表结构
- `tests/test_task_service.py`
  - 覆盖核心业务逻辑：
    - CRUD
    - 状态流转（含 done 前需子任务全部 done）
    - 最大层级限制与超限错误
    - 父任务删除保护与 cascade 行为
    - 标签过滤
    - **回归测试：循环父子关系、自引用、status_filter 非法值、parent 解绑、优先级保持等**
- `tests/test_api.py`
  - 覆盖 REST API 行为：
    - 正常创建/更新/查询/删除
    - 401/404 错误
    - 业务错误映射（如 TASK_NOT_FOUND）
    - **回归测试：API 层上的自引用、status_filter 非法值、parent 解绑、status 更新不重置 priority**

运行测试：

```bash
pytest tests/ -v
```

---

常见开发场景
------------

### 1. 新增 Task 字段

1. **修改数据层**
   - 更新 `app/models.py` 中的 `Task` 模型（选择合适的 TypeDecorator 或 PG 类型）
   - 为生产环境创建 Alembic 迁移（修改 PG Schema）：
     - `alembic revision --autogenerate -m "add xxx to tasks"`
     - 检查生成的迁移脚本，再执行 `alembic upgrade head`
2. **修改接口模型**
   - 在 `app/schemas.py` 的 `TaskCreate/TaskUpdate/TaskResponse` 中补充字段
3. **修改业务逻辑**
   - 在 `TaskService._create_task` / `_update_task` 中处理新字段
4. **修改文档**
   - 更新 `需求文档.md`（Schema + Tool 参数）
   - 更新 `API.md`
5. **补充测试**
   - 添加或更新相关单元测试 / API 测试

### 2. 新增业务规则

例如：新增一个状态、或增加更多状态流转限制：

1. 更新 `VALID_STATUSES` / `VALID_STATUS_FILTERS`
2. 根据需要扩展 `_validate_status_transition`
3. 更新文档（需求文档 2.2 + 2.3、API.md）
4. 补充单测覆盖合法/非法路径

### 3. 新增 MCP Tool

1. 在 `TaskService` 中增加业务方法
2. 在 `mcp_server.py` 中增加 `@mcp.tool()` 包装函数
3. 更新 `需求文档.md` 2.3 节中的 Tool 列表
4. 在支持 MCP 的客户端中更新配置/描述

---

代码风格与约定
--------------

- **类型标注**：所有新代码应尽量使用 Python 3.11+ 的类型标注（`list[str]` 等）
- **错误处理**：
  - 业务错误使用 `AppError(ErrorCode, message)` 抛出
  - 不在 Handler 层直接构造错误 JSON，统一交由异常处理器处理
- **异步规范**：
  - 数据库操作统一使用 `AsyncSession` 与 `await`
  - 避免在异步上下文中触发隐式 IO（比如懒加载属性），应通过 `select(...).options(selectinload(...))` 显式加载
- **日志**：
  - 使用 `structlog.get_logger()` 创建 logger
  - 日志 key 使用 snake_case，适合日志平台结构化检索

---

后续可以扩展的方向
------------------

- 增加更多查询维度（例如基于 `meta_data` 的过滤）
- 引入任务执行历史表（Audit Log）
- 接入更多嵌入来源（支持多模型切换）
- 将限流中间件替换为分布式方案（如 Redis-based limiter）

如果你计划对这些方向进行开发，推荐先在《需求文档.md》中补充相应 PRD/SDD，再按本指南的步骤迭代实现与测试。

