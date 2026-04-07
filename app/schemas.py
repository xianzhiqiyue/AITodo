import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskCommentType(str, Enum):
    COMMENT = "comment"
    PROGRESS = "progress"
    FAILURE = "failure"
    EVENT = "event"


class PublicTaskCommentType(str, Enum):
    COMMENT = "comment"
    PROGRESS = "progress"
    FAILURE = "failure"


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    status: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None
    parent_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list)
    meta_data: dict | None = None
    thinking_process: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None
    parent_id: uuid.UUID | None = None
    tags: list[str] | None = None
    meta_data: dict | None = None
    thinking_process: str | None = None

    model_config = {"extra": "forbid"}


class SubTaskInput(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None


class DecomposeRequest(BaseModel):
    sub_tasks: list[SubTaskInput] = Field(..., min_length=1)


class DecomposeSuggestion(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    rationale: str


class DecomposeSuggestionResponse(BaseModel):
    task_id: uuid.UUID
    suggestions: list[DecomposeSuggestion]


class ApplySuggestionRequest(BaseModel):
    indices: list[int] = Field(..., min_length=1)


class TaskDependencyCreate(BaseModel):
    depends_on_task_id: uuid.UUID


class TaskDependencyResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    depends_on_task_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskCommentCreate(BaseModel):
    type: PublicTaskCommentType = Field(default=PublicTaskCommentType.COMMENT)
    content: str = Field(..., min_length=1)
    meta_data: dict | None = None


class TaskCommentResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    type: TaskCommentType
    content: str
    meta_data: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ParseTaskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class ParseAndCreateTaskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    parent_id: uuid.UUID | None = None
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    force_create: bool = False
    selected_draft_index: int = Field(default=0, ge=0, le=4)
    override: "TaskDraftOverride | None" = None


class TaskDraft(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    status: str = "todo"
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    meta_data: dict = Field(default_factory=dict)


class TaskDraftOverride(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None
    tags: list[str] | None = None
    meta_data: dict | None = None


class ParseTaskResponse(BaseModel):
    draft: TaskDraft
    candidates: list[TaskDraft] = Field(default_factory=list)
    selected_index: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str
    raw_text: str


class ParseAndCreateTaskResponse(BaseModel):
    created: bool
    parse_result: ParseTaskResponse
    task: "TaskResponse | None" = None
    reason: str | None = None


class TaskResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    priority: int
    due_at: datetime | None
    parent_id: uuid.UUID | None
    tags: list[str]
    meta_data: dict
    created_at: datetime
    updated_at: datetime
    children: list["TaskResponse"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    offset: int


class TaskDependencyListResponse(BaseModel):
    dependencies: list[TaskDependencyResponse]


class ReadyTaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


class AlertItem(BaseModel):
    task: TaskResponse
    reason: str


class AlertListResponse(BaseModel):
    alerts: list[AlertItem]
    total: int


class ReminderScanResponse(BaseModel):
    scanned_at: datetime
    alerts: list[AlertItem]
    total: int


class TaskCommentListResponse(BaseModel):
    comments: list[TaskCommentResponse]


class WorkspaceDashboardResponse(BaseModel):
    today: TaskListResponse
    overdue: TaskListResponse
    blocked: TaskListResponse
    ready_to_start: ReadyTaskListResponse
    recently_updated: TaskListResponse
    alerts: AlertListResponse


class DispatchAlertsRequest(BaseModel):
    top_n: int = Field(default=20, ge=1, le=100)
    force: bool = False


class NotificationDeliveryResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    reason: str
    channel: str
    status: str
    error_message: str | None
    meta_data: dict
    sent_at: datetime

    model_config = {"from_attributes": True}


class DispatchAlertsResponse(BaseModel):
    total_candidates: int
    sent_count: int
    skipped_count: int
    failed_count: int
    deliveries: list[NotificationDeliveryResponse]


class DeleteResponse(BaseModel):
    deleted_count: int


class DecomposeResponse(BaseModel):
    parent_task: TaskResponse
    sub_tasks: list[TaskResponse]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str
    database: str
    migration: str
    parsing_service: str
    embedding_service: str
    version: str
