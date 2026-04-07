from __future__ import annotations

import uuid

from app.schemas import BlockedRecoveryResponse
from app.services.task_service import TaskService


class BlockedRecoveryService:
    def __init__(self, task_service: TaskService):
        self.task_service = task_service

    async def get_recovery_suggestions(self, task_id: uuid.UUID) -> BlockedRecoveryResponse:
        task = await self.task_service.get_task(task_id)
        dependencies = await self.task_service.list_dependencies(task_id)
        timeline = await self.task_service.list_comments(task_id)

        blockers: list[str] = []
        suggestions: list[str] = []

        if dependencies.dependencies:
            blockers.append("存在未完成或关键前置依赖。")
            suggestions.append("先检查依赖任务状态，确认是否可以推动依赖项优先完成。")

        failure_comments = [
            item.content for item in timeline.comments if item.type == "failure"
        ]
        if failure_comments:
            blockers.append("近期存在失败记录或执行异常。")
            suggestions.append("先回看最近失败记录，补齐缺失输入或修复失败原因后再恢复。")

        if task.description:
            suggestions.append("补充阻塞背景和已尝试动作，方便后续协作或 Agent 接手。")
        else:
            blockers.append("任务描述信息不足。")
            suggestions.append("先补充任务描述、期望结果和阻塞原因。")

        if not blockers:
            blockers.append("任务被标记为 blocked，但缺少明确阻塞信息。")
            suggestions.append("建议联系相关负责人或补充评论，明确外部依赖和恢复条件。")

        suggestions.append("如果仍无法推进，可拆成更小的预备任务，先处理可独立完成的部分。")
        summary = "；".join(blockers)

        return BlockedRecoveryResponse(
            task_id=task_id,
            summary=summary,
            suggestions=suggestions,
            blockers=blockers,
        )
