AI 任务调度中心 API 文档
========================

本文档描述 todoServer 提供的 REST API。  
若使用浏览器调试接口，也可以直接访问内置的 Swagger UI：`/docs`。

---

认证与错误格式
--------------

### 认证方式

除 `/health` 外，所有业务接口都需要通过 **API Key** 进行认证：

```http
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

`API_KEY` 由环境变量配置，详见 `README.md` 的配置说明。

### 错误响应格式

当请求失败时，统一返回如下结构（HTTP 状态码视具体错误而定）：

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task with id '...' does not exist."
  }
}
```

常见错误码：

| 错误码               | HTTP 状态码 | 含义                             |
|----------------------|------------|----------------------------------|
| `VALIDATION_ERROR`   | 400        | 参数校验失败                    |
| `UNAUTHORIZED`       | 401        | API Key 无效或缺失              |
| `TASK_NOT_FOUND`     | 404        | 任务不存在                      |
| `HAS_CHILDREN`       | 409        | 存在子任务，未开启 cascade 删除 |
| `PARENT_NOT_DONE`    | 409        | 子任务未全部完成，父任务无法 done |
| `MAX_DEPTH_EXCEEDED` | 422        | 超过最大嵌套层级（5 层）        |
| `RATE_LIMITED`       | 429        | 请求频率超限                    |
| `INTERNAL_ERROR`     | 500        | 服务器内部错误                  |

---

数据模型
--------

### Task 对象（TaskResponse）

```json
{
  "id": "UUID",
  "title": "string",
  "description": "string | null",
  "status": "todo | in_progress | done | blocked",
  "priority": 1,
  "due_at": "2026-03-03T12:00:00Z",
  "parent_id": "UUID | null",
  "tags": ["backend", "urgent"],
  "meta_data": {
    "thinking": "AI internal reasoning...",
    "...": "..."
  },
  "created_at": "2026-03-03T10:00:00Z",
  "updated_at": "2026-03-03T11:00:00Z",
  "children": [ /* 子任务列表，结构同 TaskResponse */ ]
}
```

关键规则：

- **状态枚举**：`todo` / `in_progress` / `done` / `blocked`
- **优先级**：`1-5`，1 为最高优先级
- **父子关系**：
  - 最多 5 层嵌套
  - 禁止形成环形引用（父不能指向自己的后代，也不能指向自己）
  - 可以通过 `parent_id = null` 来**解绑子任务**

### TaskCreate（创建任务）

```jsonc
{
  "title": "string",              // 必填，<=255
  "description": "string | null", // 可选
  "status": "todo",               // 可选，默认 "todo"
  "priority": 3,                  // 可选，默认 3，1-5
  "due_at": "2026-03-03T12:00:00Z", // 可选
  "parent_id": "UUID | null",     // 可选
  "tags": ["backend", "urgent"],  // 可选
  "meta_data": { ... },           // 可选，自由 JSON
  "thinking_process": "..."       // 可选，内部思考，会写入 meta_data.thinking
}
```

### TaskUpdate（更新任务）

```jsonc
{
  "title": "string | null",
  "description": "string | null",
  "status": "todo | in_progress | done | blocked | null",
  "priority": 1,                  // 可选，若省略则不修改
  "due_at": "2026-03-03T12:00:00Z",
  "parent_id": "UUID | null",     // 显式传 null 表示解除父子关系
  "tags": ["backend"],            // 可选
  "meta_data": { ... },           // 可选，与原有 meta_data 合并
  "thinking_process": "..."       // 可选，覆盖 meta_data.thinking
}
```

---

端点一览
--------

| 方法 | 路径                        | 说明                         |
|------|-----------------------------|------------------------------|
| GET  | `/health`                   | 健康检查（无需认证）        |
| POST | `/api/v1/tasks`             | 创建任务                     |
| PUT  | `/api/v1/tasks/{id}`        | 更新任务                     |
| GET  | `/api/v1/tasks`             | 查询任务列表（过滤/分页/搜索） |
| GET  | `/api/v1/tasks/{id}`        | 获取单个任务详情（含子任务） |
| DELETE | `/api/v1/tasks/{id}`      | 删除任务（可选 cascade）     |
| POST | `/api/v1/tasks/{id}/decompose` | 将任务拆解为多个子任务   |

下面详细说明每个端点。

---

GET /health
-----------

- **认证**：不需要
- **路径**：`/health`

**响应 200 示例：**

```json
{
  "status": "healthy",
  "database": "connected",
  "version": "1.0.0"
}
```

---

POST /api/v1/tasks
------------------

创建新任务。

- **方法**：`POST`
- **路径**：`/api/v1/tasks`
- **认证**：需要 API Key
- **请求体**：`TaskCreate`
- **成功状态码**：`201 Created`

**请求示例：**

```http
POST /api/v1/tasks HTTP/1.1
Authorization: Bearer <API_KEY>
Content-Type: application/json

{
  "title": "写 README",
  "description": "为 AI 任务调度中心写 README 与 API 文档",
  "priority": 2,
  "tags": ["docs", "urgent"]
}
```

**响应 201 示例：**

返回 `TaskResponse`。

---

PUT /api/v1/tasks/{id}
----------------------

更新已有任务的部分字段。

- **方法**：`PUT`
- **路径**：`/api/v1/tasks/{id}`
- **认证**：需要 API Key
- **请求体**：`TaskUpdate`

注意：

- 未提供的字段保持不变。
- 若仅更新 `status`，不会重置 `priority` 等其它字段。
- 若显式传 `{ "parent_id": null }`，会解绑父子关系。

**请求示例：**

```http
PUT /api/v1/tasks/xxxx-... HTTP/1.1
Authorization: Bearer <API_KEY>
Content-Type: application/json

{
  "status": "in_progress"
}
```

**响应 200**：更新后的 `TaskResponse`。

可能错误：

- `400 VALIDATION_ERROR`：状态非法 / parent_id 形成环 / status_filter 非法（通过 `get_task_context` 时）
- `404 TASK_NOT_FOUND`：任务不存在
- `409 PARENT_NOT_DONE`：父任务设置为 done 时，存在未完成子任务
- `422 MAX_DEPTH_EXCEEDED`：超过最大 5 层嵌套

---

GET /api/v1/tasks
-----------------

查询任务列表，支持状态过滤、标签过滤、语义/关键词搜索以及分页。

- **方法**：`GET`
- **路径**：`/api/v1/tasks`
- **认证**：需要 API Key

### 查询参数

| 参数名         | 类型             | 默认值   | 说明 |
|----------------|------------------|----------|------|
| `status_filter`| string           | `open`   | 任务状态过滤器，可选值：`open`（todo+in_progress）、`todo`、`in_progress`、`done`、`blocked`、`all` |
| `top_n`        | int              | `20`     | 返回条数上限，范围 `1-100` |
| `offset`       | int              | `0`      | 分页偏移量 |
| `tags`         | array\[string]   | `None`   | 标签过滤，返回至少包含其中一个标签的任务 |
| `query`        | string           | `None`   | 搜索关键词：若配置了嵌入服务则使用语义搜索，否则回退为标题关键词搜索 |
| `parent_id`    | UUID             | `None`   | 若提供，仅返回该父任务下的直接子任务 |

> **注意**：`status_filter` 传入非法值会返回 `400 VALIDATION_ERROR`，不会静默变成 `all`。

### 响应

```json
{
  "tasks": [ /* TaskResponse[] */ ],
  "total": 42,
  "offset": 0
}
```

**示例：获取所有未完成任务**

```http
GET /api/v1/tasks?status_filter=open&top_n=20 HTTP/1.1
Authorization: Bearer <API_KEY>
```

---

GET /api/v1/tasks/{id}
----------------------

获取单个任务详情。

- **方法**：`GET`
- **路径**：`/api/v1/tasks/{id}`
- **认证**：需要 API Key

**响应 200**：`TaskResponse`，其中 `children` 字段包含所有直接子任务。

**错误**：

- `404 TASK_NOT_FOUND`：任务不存在

---

DELETE /api/v1/tasks/{id}
-------------------------

删除任务，可选择是否级联删除子任务。

- **方法**：`DELETE`
- **路径**：`/api/v1/tasks/{id}`
- **认证**：需要 API Key

### 查询参数

| 参数名    | 类型   | 默认值 | 说明 |
|-----------|--------|--------|------|
| `cascade` | bool   | `false`| 是否级联删除所有后代任务 |

### 行为说明

- 当 `cascade=false` 时：
  - 若该任务存在任意子任务（任意层级），则返回 `409 HAS_CHILDREN`，并不删除任何任务。
- 当 `cascade=true` 时：
  - 删除该任务及其所有后代，`deleted_count` 包含总共删除的数量。

**响应 200 示例：**

```json
{
  "deleted_count": 3
}
```

---

POST /api/v1/tasks/{id}/decompose
---------------------------------

将一个大任务拆解为多个子任务。

- **方法**：`POST`
- **路径**：`/api/v1/tasks/{id}/decompose`
- **认证**：需要 API Key

### 请求体（DecomposeRequest）

```jsonc
{
  "sub_tasks": [
    {
      "title": "子任务 1",
      "description": "可选",
      "priority": 3,
      "due_at": "2026-03-03T12:00:00Z"
    },
    {
      "title": "子任务 2"
    }
  ]
}
```

### 响应

```json
{
  "parent_task": { /* TaskResponse */ },
  "sub_tasks": [ /* TaskResponse[] */ ]
}
```

若拆解后超过最大嵌套层级，会返回：

- `422 MAX_DEPTH_EXCEEDED`

---

速率限制
--------

所有经过 `RateLimitMiddleware` 的请求都会受到限制：

- **窗口大小**：60 秒
- **每个 key 限制**：100 请求 / 分钟
- **key 维度**：
  - 优先使用 `Authorization: Bearer <token>` 中的 token
  - 若缺失/格式错误，则使用 `"anonymous"` 作为 key

当超过限制时：

- 返回 `429 RATE_LIMITED`，错误信息为 `"Too many requests. Please slow down."`

中间件内部会定期清理过期的 key，以防止内存无限增长。

---

附录：典型调用示例（curl）
--------------------------

```bash
API=http://localhost:8000
KEY=your-secure-api-key

# 创建任务
curl -X POST "$API/api/v1/tasks" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "写周报",
    "priority": 2,
    "tags": ["work", "weekly"]
  }'

# 查询所有未完成任务
curl "$API/api/v1/tasks?status_filter=open&top_n=20" \
  -H "Authorization: Bearer $KEY"
```

