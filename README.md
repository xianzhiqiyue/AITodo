# AITodo

一个面向 AI Agent 的任务中心后端，提供 REST API 和 MCP 工具两种接入方式。

## 当前能力

- 任务 CRUD
- 父子任务层级与递归拆解
- 状态流转与完成约束
- 自然语言任务解析为结构化草稿
- 解析后按置信度门槛安全入库
- 任务依赖关系与 `ready-to-start` 视图
- 评论 / 时间线、工作台告警与提醒扫描
- 工作台总览 dashboard 接口
- 主动告警分发与 webhook 通知记录
- 今日建议任务、阻塞恢复建议、周期回顾总结
- AI 拆解建议与确认创建
- AI 拆解建议支持推荐顺序和自动依赖落库
- API Key 鉴权与基础限流
- Request ID、慢请求日志、增强健康检查
- PostgreSQL + pgvector 语义检索
- MCP tools: `upsert_task`、`get_task_context`、`delete_task`、`decompose_task`、`parse_task_input`、`parse_and_create_task`
- MCP tools: `add_task_dependency`、`list_task_dependencies`、`remove_task_dependency`、`get_ready_to_start_tasks`
- MCP tools: `add_task_comment`、`get_task_timeline`、`get_workspace_today`、`get_workspace_overdue`、`get_workspace_blocked`、`get_workspace_recently_updated`、`get_workspace_alerts`
- MCP tools: `get_workspace_dashboard`、`dispatch_alert_notifications`
- MCP tools: `suggest_task_decomposition`、`apply_task_suggestions`、`scan_reminders`
- MCP tools: `plan_task_execution`、`apply_task_plan`、`get_suggested_today_tasks`、`get_stale_tasks`、`get_task_recovery_suggestions`、`get_review_summary`、`test_notification_channel`

## 本地启动

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 配置环境变量

```bash
cp .env.example .env
```

3. 启动 PostgreSQL

```bash
docker compose up -d db
```

4. 执行迁移并启动 API

```bash
python -m alembic upgrade head
uvicorn main:app --reload
```

服务默认监听 `http://127.0.0.1:8000`，OpenAPI 文档地址为 `/docs`。

如果只想用 SQLite 本地跑通：

```bash
export DATABASE_URL=sqlite+aiosqlite:///./aitodo.db
python -m alembic upgrade head
uvicorn main:app --reload
```

说明：
- PostgreSQL 会启用 `pgvector`、GIN tags 索引和向量索引。
- SQLite 会自动降级到文本/JSON fallback，适合本地开发和测试，不适合生产向量检索场景。

可选通知配置：

```bash
export NOTIFICATION_WEBHOOK_URL=https://example.com/webhook
export NOTIFICATION_DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
export NOTIFICATION_REPEAT_WINDOW_HOURS=6
```

## Docker 启动

```bash
docker compose up --build
```

## 认证

所有 `/api/v1/*` 请求都需要：

```http
Authorization: Bearer <API_KEY>
```

`/health` 不需要鉴权。

## 测试

```bash
pytest -q
```

迁移 smoke test 也已纳入测试集，会在 SQLite 上执行一次 `alembic upgrade head` 和 `downgrade base`。

CI 也会自动执行：

```bash
python -m compileall app main.py mcp_server.py
pytest -q
```

如果缺少测试依赖，先重新执行：

```bash
pip install -r requirements.txt
```

## MCP Server

通过 stdio 运行：

```bash
python mcp_server.py
```

适合让支持 MCP 的 Agent 直接查询和更新任务上下文。

## 自然语言解析

REST:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/parse \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"下周给老王发项目报告，并补充风险说明"}'
```

接口返回结构化任务草稿，不直接入库。配置 `PARSING_API_KEY` 后优先走 LLM 解析；未配置时自动降级到本地启发式解析。

安全入库：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/parse-and-create \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"明天补后端测试并提交报告","force_create":true}'
```

默认会检查解析置信度，低于 `min_confidence` 时只返回草稿和原因，不会直接落库。

也支持选择候选草稿并覆盖字段：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/parse-and-create \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text":"明天补后端测试并提交报告，给团队同步",
    "force_create":true,
    "selected_draft_index":1,
    "override":{
      "title":"同步测试结果",
      "priority":2,
      "tags":["backend","sync"]
    }
  }'
```

## 任务依赖

创建依赖：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/<TASK_ID>/dependencies \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"depends_on_task_id":"<DEPENDENCY_TASK_ID>"}'
```

查询当前可启动任务：

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/workspace/ready-to-start?top_n=20" \
  -H "Authorization: Bearer $API_KEY"
```

## 工作台总览

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/workspace/dashboard?top_n=10" \
  -H "Authorization: Bearer $API_KEY"
```

会一次性返回 `today / overdue / blocked / ready_to_start / recently_updated / alerts / suggested_today / stale_tasks`。

## AI 拆解建议

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/tasks/<TASK_ID>/decompose/suggestions" \
  -H "Authorization: Bearer $API_KEY"
```

返回的建议项会包含：
- `order`
- `depends_on_indices`

调用 `apply-suggestions` 时，如果选中的建议之间存在推荐依赖，系统会在创建子任务后自动补齐任务依赖关系。

也支持先生成完整计划，再确认落库：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/tasks/<TASK_ID>/plan" \
  -H "Authorization: Bearer $API_KEY"
```

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/tasks/<TASK_ID>/apply-plan" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"indices":[0,1,2]}'
```

## 今日建议与阻塞恢复

建议优先处理任务：

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/workspace/suggested-today?top_n=10" \
  -H "Authorization: Bearer $API_KEY"
```

阻塞恢复建议：

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/tasks/<TASK_ID>/recovery-suggestions" \
  -H "Authorization: Bearer $API_KEY"
```

周期回顾总结：

```bash
curl -X GET "http://127.0.0.1:8000/api/v1/reviews/summary?from_date=2026-04-01T00:00:00Z&to_date=2026-04-07T23:59:59Z" \
  -H "Authorization: Bearer $API_KEY"
```

## 主动通知

手动触发当前 alerts 的 webhook 分发：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/notifications/dispatch-alerts" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"top_n":20,"force":false}'
```

如果未配置 `NOTIFICATION_WEBHOOK_URL`，接口会返回校验错误。

也支持测试指定通知渠道：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/notifications/test" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"channel":"dingtalk","message":"AITodo test"}'
```

## 健康检查与观测

- 所有响应都会附带 `X-Request-ID`
- 超过 `SLOW_REQUEST_THRESHOLD_MS` 的请求会写慢请求日志
- `/health` 会返回数据库、迁移、解析服务、embedding 服务和版本信息
