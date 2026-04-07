from __future__ import annotations

import uuid

from app.schemas import (
    ParseAndCreateTaskResponse,
    ParseTaskResponse,
    TaskCreate,
    TaskDraft,
    TaskDraftOverride,
    TaskResponse,
)
from app.services.task_parsing_service import TaskParsingService
from app.services.task_service import TaskService


class TaskIntakeService:
    def __init__(
        self,
        task_service: TaskService,
        parsing_service: TaskParsingService,
    ):
        self.task_service = task_service
        self.parsing_service = parsing_service

    async def parse(self, text: str) -> ParseTaskResponse:
        return await self.parsing_service.parse_text(text)

    async def parse_and_create(
        self,
        *,
        text: str,
        parent_id: uuid.UUID | None = None,
        min_confidence: float = 0.6,
        force_create: bool = False,
        selected_draft_index: int = 0,
        override: TaskDraftOverride | None = None,
    ) -> ParseAndCreateTaskResponse:
        parse_result = await self.parsing_service.parse_text(text)
        candidate = self._select_draft(parse_result, selected_draft_index)
        final_draft = self._apply_override(candidate, override)

        if not force_create and parse_result.confidence < min_confidence:
            return ParseAndCreateTaskResponse(
                created=False,
                parse_result=parse_result,
                reason=(
                    f"Parse confidence {parse_result.confidence:.2f} is below "
                    f"the required threshold {min_confidence:.2f}."
                ),
            )

        created_task = await self.task_service.upsert_task(
            data=TaskCreate(
                title=final_draft.title,
                description=final_draft.description,
                status=final_draft.status,
                priority=final_draft.priority,
                due_at=final_draft.due_at,
                parent_id=parent_id,
                tags=final_draft.tags,
                meta_data={
                    **final_draft.meta_data,
                    "parse_source": parse_result.source,
                    "parse_confidence": parse_result.confidence,
                    "parse_raw_text": parse_result.raw_text,
                    "selected_draft_index": selected_draft_index,
                },
            )
        )
        return ParseAndCreateTaskResponse(
            created=True,
            parse_result=parse_result,
            task=TaskResponse.model_validate(created_task),
        )

    def _select_draft(self, parse_result: ParseTaskResponse, selected_draft_index: int) -> TaskDraft:
        if not parse_result.candidates:
            return parse_result.draft
        if selected_draft_index >= len(parse_result.candidates):
            return parse_result.draft
        return parse_result.candidates[selected_draft_index]

    def _apply_override(
        self,
        draft: TaskDraft,
        override: TaskDraftOverride | None,
    ) -> TaskDraft:
        if override is None:
            return draft

        provided_fields = override.model_fields_set
        return TaskDraft(
            title=override.title if "title" in provided_fields and override.title is not None else draft.title,
            description=override.description if "description" in provided_fields else draft.description,
            status=override.status if "status" in provided_fields and override.status is not None else draft.status,
            priority=override.priority if "priority" in provided_fields and override.priority is not None else draft.priority,
            due_at=override.due_at if "due_at" in provided_fields else draft.due_at,
            tags=override.tags if "tags" in provided_fields and override.tags is not None else draft.tags,
            meta_data={
                **draft.meta_data,
                **(override.meta_data or {}),
            } if "meta_data" in provided_fields else draft.meta_data,
        )
