import json
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, TypeDecorator, func, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StringList(TypeDecorator):
    """PostgreSQL ARRAY(Text) with JSON fallback for SQLite."""
    impl = types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY
            return dialect.type_descriptor(ARRAY(Text))
        return dialect.type_descriptor(types.Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if value is None:
            return "[]"
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value or []
        if value is None:
            return []
        return json.loads(value)


class FlexibleJSON(TypeDecorator):
    """PostgreSQL JSONB with JSON fallback for SQLite."""
    impl = types.Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(types.Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if value is None:
            return "{}"
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value or {}
        if value is None:
            return {}
        if isinstance(value, str):
            return json.loads(value)
        return value


class FlexibleUUID(TypeDecorator):
    """PostgreSQL UUID with String(36) fallback for SQLite."""
    impl = types.String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(types.String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class OptionalVector(TypeDecorator):
    """PostgreSQL pgvector Vector with Text fallback for SQLite."""
    impl = types.Text
    cache_ok = True

    def __init__(self, dim: int = 1536):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(types.Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, str):
            return json.loads(value)
        return value


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        FlexibleUUID(), ForeignKey("tasks.id"), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(
        StringList(), default=list, nullable=False
    )
    meta_data: Mapped[dict] = mapped_column(
        FlexibleJSON(), default=dict, nullable=False
    )
    embedding = mapped_column(OptionalVector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    children: Mapped[list["Task"]] = relationship(
        "Task", back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped["Task | None"] = relationship(
        "Task", back_populates="children", remote_side=[id]
    )
    dependencies: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        back_populates="task",
        foreign_keys="TaskDependency.task_id",
        cascade="all, delete-orphan",
    )
    dependent_links: Mapped[list["TaskDependency"]] = relationship(
        "TaskDependency",
        back_populates="depends_on_task",
        foreign_keys="TaskDependency.depends_on_task_id",
        cascade="all, delete-orphan",
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), ForeignKey("tasks.id"), nullable=False
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), ForeignKey("tasks.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="dependencies",
        foreign_keys=[task_id],
    )
    depends_on_task: Mapped["Task"] = relationship(
        "Task",
        back_populates="dependent_links",
        foreign_keys=[depends_on_task_id],
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), ForeignKey("tasks.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="comment")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta_data: Mapped[dict] = mapped_column(
        FlexibleJSON(), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship("Task")


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), ForeignKey("tasks.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_data: Mapped[dict] = mapped_column(
        FlexibleJSON(), default=dict, nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship("Task")

class ObsidianSyncConnection(Base):
    __tablename__ = "obsidian_sync_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    vault_id: Mapped[str] = mapped_column(String(120), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_name: Mapped[str] = mapped_column(String(120), nullable=False, default="AI-TODO-SERVER")
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checkpoint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_data: Mapped[dict] = mapped_column(FlexibleJSON(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ObsidianFileBinding(Base):
    __tablename__ = "obsidian_file_bindings"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vault_id: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(4096), nullable=False)
    file_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    last_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_data: Mapped[dict] = mapped_column(FlexibleJSON(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

class ObsidianTaskIndex(Base):
    __tablename__ = "obsidian_task_index"

    id: Mapped[uuid.UUID] = mapped_column(
        FlexibleUUID(), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[str] = mapped_column(String(120), nullable=False)
    vault_id: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(4096), nullable=False)
    file_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list[str]] = mapped_column(StringList(), default=list, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    depends_on: Mapped[list[str]] = mapped_column(StringList(), default=list, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    meta_data: Mapped[dict] = mapped_column(FlexibleJSON(), default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
