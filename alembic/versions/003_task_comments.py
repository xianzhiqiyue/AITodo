"""task comments

Revision ID: 003
Revises: 002
Create Date: 2026-04-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36)
    meta_data_type = postgresql.JSONB() if dialect == "postgresql" else sa.Text()

    op.create_table(
        "task_comments",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False, server_default="comment"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta_data", meta_data_type, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_task_comments_task_id", "task_comments", ["task_id"])


def downgrade() -> None:
    op.drop_index("idx_task_comments_task_id", table_name="task_comments")
    op.drop_table("task_comments")
