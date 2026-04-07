from __future__ import annotations

import uuid

from app.errors import AppError, ErrorCode
from app.schemas import DecomposeSuggestion, DecomposeSuggestionResponse, SubTaskInput, TaskPlanResponse
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
                    DecomposeSuggestion(
                        title="梳理发布清单",
                        priority=1,
                        rationale="先确认发布范围和检查项。",
                        order=1,
                    ),
                    DecomposeSuggestion(
                        title="执行预发验证",
                        priority=1,
                        rationale="发布前需要验证关键路径。",
                        order=2,
                        depends_on_indices=[0],
                    ),
                    DecomposeSuggestion(
                        title="完成正式发布与回滚预案",
                        priority=2,
                        rationale="确保上线和异常处理都有准备。",
                        order=3,
                        depends_on_indices=[1],
                    ),
                ]
            )
        elif any(token in text for token in ["报告", "report", "文档", "docs"]):
            suggestions.extend(
                [
                    DecomposeSuggestion(
                        title="收集输入材料",
                        priority=1,
                        rationale="先整理写作所需信息。",
                        order=1,
                    ),
                    DecomposeSuggestion(
                        title="输出初稿",
                        priority=2,
                        rationale="先完成主体内容。",
                        order=2,
                        depends_on_indices=[0],
                    ),
                    DecomposeSuggestion(
                        title="评审并发送",
                        priority=2,
                        rationale="确保对外输出前有检查。",
                        order=3,
                        depends_on_indices=[1],
                    ),
                ]
            )
        else:
            suggestions.extend(
                [
                    DecomposeSuggestion(
                        title="明确范围与目标",
                        priority=1,
                        rationale="先缩小任务边界。",
                        order=1,
                    ),
                    DecomposeSuggestion(
                        title="执行核心工作",
                        priority=2,
                        rationale="处理中间产出。",
                        order=2,
                        depends_on_indices=[0],
                    ),
                    DecomposeSuggestion(
                        title="验收与收尾",
                        priority=2,
                        rationale="补齐检查和交付。",
                        order=3,
                        depends_on_indices=[1],
                    ),
                ]
            )

        return DecomposeSuggestionResponse(task_id=task_id, suggestions=suggestions)

    async def generate_plan(self, task_id: uuid.UUID) -> TaskPlanResponse:
        task = await self.task_service.get_task(task_id)
        suggestion_result = await self.suggest_decomposition(task_id)

        risks: list[str] = []
        assumptions: list[str] = []
        if task.due_at is not None:
            risks.append("任务存在截止时间，建议优先确认关键路径和缓冲时间。")
        if not task.description:
            assumptions.append("当前任务描述较少，计划基于标题推断。")
        if task.status == "blocked":
            risks.append("任务当前处于 blocked，需要先确认阻塞原因。")

        return TaskPlanResponse(
            task_id=task_id,
            goal=task.title,
            suggestions=suggestion_result.suggestions,
            risks=risks,
            assumptions=assumptions,
        )

    async def apply_suggestions(
        self,
        task_id: uuid.UUID,
        indices: list[int],
    ):
        suggestion_result = await self.suggest_decomposition(task_id)
        selected: list[SubTaskInput] = []
        selected_index_map: dict[int, int] = {}
        for index in indices:
            if index < 0 or index >= len(suggestion_result.suggestions):
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Suggestion index {index} is out of range.",
                )
            suggestion = suggestion_result.suggestions[index]
            selected_index_map[index] = len(selected)
            selected.append(
                SubTaskInput(
                    title=suggestion.title,
                    description=suggestion.description,
                    priority=suggestion.priority,
                )
            )
        result = await self.task_service.decompose_task(task_id, selected)

        for original_index, selected_position in selected_index_map.items():
            suggestion = suggestion_result.suggestions[original_index]
            for dependency_index in suggestion.depends_on_indices:
                if dependency_index in selected_index_map:
                    await self.task_service.add_dependency(
                        result.sub_tasks[selected_position].id,
                        result.sub_tasks[selected_index_map[dependency_index]].id,
                    )

        return result

    async def apply_plan(self, task_id: uuid.UUID, indices: list[int] | None = None):
        plan = await self.generate_plan(task_id)
        selected_indices = indices or list(range(len(plan.suggestions)))
        return await self.apply_suggestions(task_id, selected_indices)
