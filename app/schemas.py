import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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


class SubTaskInput(BaseModel):
    title: str = Field(..., max_length=255)
    description: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None


class DecomposeRequest(BaseModel):
    sub_tasks: list[SubTaskInput] = Field(..., min_length=1)


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
    version: str
