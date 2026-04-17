"""obsidian task index

Revision ID: 006
Revises: 005
Create Date: 2026-04-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type(dialect: str):
    return postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36)


def _json_type(dialect: str):
    return postgresql.JSONB() if dialect == "postgresql" else sa.Text()


def _string_list_type(dialect: str):
    return postgresql.ARRAY(sa.Text()) if dialect == "postgresql" else sa.Text()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "obsidian_task_index",
        sa.Column("id", _uuid_type(dialect), primary_key=True),
        sa.Column("task_id", sa.String(length=120), nullable=False),
        sa.Column("vault_id", sa.String(length=120), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("file_id", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", _string_list_type(dialect), nullable=False, server_default="{}" if dialect == "postgresql" else "[]"),
        sa.Column("parent_id", sa.String(length=120), nullable=True),
        sa.Column("depends_on", _string_list_type(dialect), nullable=False, server_default="{}" if dialect == "postgresql" else "[]"),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("meta_data", _json_type(dialect), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vault_id", "task_id", name="uq_obsidian_task_index_vault_task"),
    )
    op.create_index("idx_obsidian_task_index_vault_path", "obsidian_task_index", ["vault_id", "path"])
    op.create_index("idx_obsidian_task_index_status", "obsidian_task_index", ["status"])


def downgrade() -> None:
    op.drop_index("idx_obsidian_task_index_status", table_name="obsidian_task_index")
    op.drop_index("idx_obsidian_task_index_vault_path", table_name="obsidian_task_index")
    op.drop_table("obsidian_task_index")
