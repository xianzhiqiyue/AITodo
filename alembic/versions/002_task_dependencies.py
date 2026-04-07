"""task dependencies

Revision ID: 002
Revises: 001
Create Date: 2026-04-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(length=36)

    op.create_table(
        "task_dependencies",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("task_id", uuid_type, nullable=False),
        sa.Column("depends_on_task_id", uuid_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency_pair"),
    )
    op.create_index("idx_task_dependencies_task_id", "task_dependencies", ["task_id"])
    op.create_index(
        "idx_task_dependencies_depends_on_task_id",
        "task_dependencies",
        ["depends_on_task_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_task_dependencies_depends_on_task_id", table_name="task_dependencies")
    op.drop_index("idx_task_dependencies_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")
