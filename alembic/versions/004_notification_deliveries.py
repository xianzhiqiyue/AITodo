"""notification deliveries

Revision ID: 004
Revises: 003
Create Date: 2026-04-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36)
    meta_data_type = postgresql.JSONB() if dialect == "postgresql" else sa.Text()

    op.create_table(
        "notification_deliveries",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("meta_data", meta_data_type, nullable=False, server_default="{}"),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_notification_deliveries_task_id", "notification_deliveries", ["task_id"])
    op.create_index("idx_notification_deliveries_sent_at", "notification_deliveries", ["sent_at"])


def downgrade() -> None:
    op.drop_index("idx_notification_deliveries_sent_at", table_name="notification_deliveries")
    op.drop_index("idx_notification_deliveries_task_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
