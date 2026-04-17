"""obsidian sync bindings

Revision ID: 005
Revises: 004
Create Date: 2026-04-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_type(dialect: str):
    return postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36)


def _json_type(dialect: str):
    return postgresql.JSONB() if dialect == "postgresql" else sa.Text()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    uuid_type = _uuid_type(dialect)
    json_type = _json_type(dialect)

    op.create_table(
        "obsidian_sync_connections",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("vault_id", sa.String(length=120), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=False, server_default="AI-TODO-SERVER"),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checkpoint", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("meta_data", json_type, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_obsidian_sync_connections_status", "obsidian_sync_connections", ["status"])

    op.create_table(
        "obsidian_file_bindings",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=False),
        sa.Column("vault_id", sa.String(length=120), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("file_id", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_data", json_type, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("entity_type", "entity_id", "vault_id", name="uq_obsidian_file_bindings_entity_vault"),
    )
    op.create_index("idx_obsidian_file_bindings_path", "obsidian_file_bindings", ["vault_id", "path"])
    op.create_index("idx_obsidian_file_bindings_file_id", "obsidian_file_bindings", ["file_id"])


def downgrade() -> None:
    op.drop_index("idx_obsidian_file_bindings_file_id", table_name="obsidian_file_bindings")
    op.drop_index("idx_obsidian_file_bindings_path", table_name="obsidian_file_bindings")
    op.drop_table("obsidian_file_bindings")
    op.drop_index("idx_obsidian_sync_connections_status", table_name="obsidian_sync_connections")
    op.drop_table("obsidian_sync_connections")
