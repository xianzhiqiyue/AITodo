from __future__ import annotations

import uuid

from app.errors import AppError, ErrorCode
from app.schemas import DecomposeSuggestion, DecomposeSuggestionResponse, SubTaskInput
from app.services.task_service import TaskService


class TaskPlanningService:
    def __init__(self, task_service: TaskService):
        self.task_service = task_service

    async def suggest_decomposition(self, task_id: uuid.UUID) -> DecomposeSuggestionResponse:
        task = await self.task_service.get_task(task_id)
        text = f"{task.title}\n{task.description or ''}".lower()

        suggestions: list[DecomposeSuggestion] = []
        if any(token in text for token in ["发布", "deploy", "deployment"]):
            suggestions.extend(
                [
                    DecomposeSuggestion(title="梳理发布清单", priority=1, rationale="先确认发布范围和检查项。"),
                    DecomposeSuggestion(title="执行预发验证", priority=1, rationale="发布前需要验证关键路径。"),
                    DecomposeSuggestion(title="完成正式发布与回滚预案", priority=2, rationale="确保上线和异常处理都有准备。"),
                ]
            )
        elif any(token in text for token in ["报告", "report", "文档", "docs"]):
            suggestions.extend(
                [
                    DecomposeSuggestion(title="收集输入材料", priority=1, rationale="先整理写作所需信息。"),
                    DecomposeSuggestion(title="输出初稿", priority=2, rationale="先完成主体内容。"),
                    DecomposeSuggestion(title="评审并发送", priority=2, rationale="确保对外输出前有检查。"),
                ]
            )
        else:
            suggestions.extend(
                [
                    DecomposeSuggestion(title="明确范围与目标", priority=1, rationale="先缩小任务边界。"),
                    DecomposeSuggestion(title="执行核心工作", priority=2, rationale="处理中间产出。"),
                    DecomposeSuggestion(title="验收与收尾", priority=2, rationale="补齐检查和交付。"),
                ]
            )

        return DecomposeSuggestionResponse(task_id=task_id, suggestions=suggestions)

    async def apply_suggestions(
        self,
        task_id: uuid.UUID,
        indices: list[int],
    ):
        suggestion_result = await self.suggest_decomposition(task_id)
        selected: list[SubTaskInput] = []
        for index in indices:
            if index < 0 or index >= len(suggestion_result.suggestions):
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Suggestion index {index} is out of range.",
                )
            suggestion = suggestion_result.suggestions[index]
            selected.append(
                SubTaskInput(
                    title=suggestion.title,
                    description=suggestion.description,
                    priority=suggestion.priority,
                )
            )
        return await self.task_service.decompose_task(task_id, selected)
