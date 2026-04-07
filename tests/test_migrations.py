from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_head_supports_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "alembic.sqlite"
    async_db_url = f"sqlite+aiosqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", async_db_url)
    get_settings.cache_clear()

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))

    command.upgrade(alembic_config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    assert {"tasks", "task_dependencies", "task_comments", "notification_deliveries"}.issubset(inspector.get_table_names())
    assert {"idx_tasks_status", "idx_tasks_parent_id", "idx_tasks_tags", "idx_tasks_embedding"}.issubset(
        {index["name"] for index in inspector.get_indexes("tasks")}
    )
    assert {"idx_task_dependencies_task_id", "idx_task_dependencies_depends_on_task_id"}.issubset(
        {index["name"] for index in inspector.get_indexes("task_dependencies")}
    )
    assert {"idx_task_comments_task_id"}.issubset(
        {index["name"] for index in inspector.get_indexes("task_comments")}
    )
    assert {"idx_notification_deliveries_task_id", "idx_notification_deliveries_sent_at"}.issubset(
        {index["name"] for index in inspector.get_indexes("notification_deliveries")}
    )

    command.downgrade(alembic_config, "base")

    inspector = inspect(engine)
    assert "tasks" not in inspector.get_table_names()

    get_settings.cache_clear()
