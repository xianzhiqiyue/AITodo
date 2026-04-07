---
name: aitodo
version: 0.1.0
description: AI-first 任务中枢后端，提供 REST 与 MCP 接口、任务管理、自然语言任务解析、AI 拆解、依赖调度、通知与工作台聚合能力。
author: Zhuyue <zhuyue314@gmail.com>
category: productivity
tags:
  - api
  - mcp
  - backend
  - automation
---

# AITodo Skill

此项目是一个可交付给 AI 助手调用的任务管理 Skill：

- FastAPI 后端服务，支持任务 CRUD 与状态机
- 自然语言任务解析与确认入库
- 任务拆解、依赖关系与执行建议
- Workspace 聚合视图与告警
- MCP 服务与多渠道通知

## 快速上手

`/api/v1` 下的 REST 接口和 MCP 工具可直接复用当前仓库服务运行能力。

