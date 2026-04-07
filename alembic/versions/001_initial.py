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
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        id_type = postgresql.UUID(as_uuid=True)
        parent_id_type = postgresql.UUID(as_uuid=True)
        tags_type = postgresql.ARRAY(sa.Text())
        tags_default = "{}"
        meta_data_type = postgresql.JSONB()
        meta_data_default = "{}"
        embedding_type = Vector(1536)
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    else:
        id_type = sa.String(length=36)
        parent_id_type = sa.String(length=36)
        tags_type = sa.Text()
        tags_default = "[]"
        meta_data_type = sa.Text()
        meta_data_default = "{}"
        embedding_type = sa.Text()

    op.create_table(
        "tasks",
        sa.Column("id", id_type, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parent_id",
            parent_id_type,
            sa.ForeignKey("tasks.id"),
            nullable=True,
        ),
        sa.Column(
            "tags",
            tags_type,
            nullable=False,
            server_default=tags_default,
        ),
        sa.Column(
            "meta_data",
            meta_data_type,
            nullable=False,
            server_default=meta_data_default,
        ),
        sa.Column("embedding", embedding_type, nullable=True),
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
    if dialect == "postgresql":
        op.create_index(
            "idx_tasks_tags", "tasks", ["tags"], postgresql_using="gin"
        )
        op.execute(
            "CREATE INDEX idx_tasks_embedding ON tasks "
            "USING hnsw (embedding vector_cosine_ops)"
        )
    else:
        op.create_index("idx_tasks_tags", "tasks", ["tags"])
        op.create_index("idx_tasks_embedding", "tasks", ["embedding"])


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.drop_index("idx_tasks_embedding", table_name="tasks")
    op.drop_index("idx_tasks_tags", table_name="tasks")
    op.drop_index("idx_tasks_parent_id", table_name="tasks")
    op.drop_index("idx_tasks_status", table_name="tasks")
    op.drop_table("tasks")
    if dialect == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
