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
