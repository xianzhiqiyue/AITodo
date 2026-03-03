"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id"),
            nullable=True,
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "meta_data",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "idx_tasks_status", "tasks", ["status"]
    )
    op.create_index(
        "idx_tasks_parent_id", "tasks", ["parent_id"]
    )
    op.create_index(
        "idx_tasks_tags", "tasks", ["tags"], postgresql_using="gin"
    )
    op.execute(
        "CREATE INDEX idx_tasks_embedding ON tasks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.execute("DROP EXTENSION IF EXISTS vector")
