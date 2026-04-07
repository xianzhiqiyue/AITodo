import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from pydantic import ValidationError

import app.services.task_service as task_service_module
from app.errors import AppError, ErrorCode
from app.schemas import SubTaskInput, TaskCommentCreate, TaskCreate, TaskUpdate
from app.services.task_service import TaskService


pytestmark = pytest.mark.asyncio


async def test_create_task(task_service: TaskService):
    result = await task_service.upsert_task(
        data=TaskCreate(title="Test task", priority=2, tags=["backend"])
    )
    assert result.title == "Test task"
    assert result.status == "todo"
    assert result.priority == 2
    assert "backend" in result.tags


async def test_update_task(task_service: TaskService):
    created = await task_service.upsert_task(
        data=TaskCreate(title="Original")
    )
    updated = await task_service.upsert_task(
        update_data=TaskUpdate(title="Updated", status="in_progress"),
        task_id=created.id,
    )
    assert updated.title == "Updated"
    assert updated.status == "in_progress"


async def test_get_task(task_service: TaskService):
    created = await task_service.upsert_task(
        data=TaskCreate(title="Fetch me")
    )
    fetched = await task_service.get_task(created.id)
    assert fetched.id == created.id
    assert fetched.title == "Fetch me"


async def test_get_task_not_found(task_service: TaskService):
    with pytest.raises(AppError) as exc_info:
        await task_service.get_task(uuid.uuid4())
    assert exc_info.value.code == ErrorCode.TASK_NOT_FOUND


async def test_list_tasks_filter(task_service: TaskService):
    await task_service.upsert_task(data=TaskCreate(title="Task A"))
    await task_service.upsert_task(data=TaskCreate(title="Task B", status="done"))

    open_tasks = await task_service.get_task_context(status_filter="open")
    assert open_tasks.total >= 1
    for t in open_tasks.tasks:
        assert t.status in ("todo", "in_progress")


async def test_delete_task(task_service: TaskService):
    created = await task_service.upsert_task(data=TaskCreate(title="To delete"))
    result = await task_service.delete_task(created.id)
    assert result.deleted_count == 1

    with pytest.raises(AppError):
        await task_service.get_task(created.id)


async def test_delete_task_with_children_blocked(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="Parent"))
    await task_service.upsert_task(
        data=TaskCreate(title="Child", parent_id=parent.id)
    )

    with pytest.raises(AppError) as exc_info:
        await task_service.delete_task(parent.id, cascade=False)
    assert exc_info.value.code == ErrorCode.HAS_CHILDREN


async def test_delete_task_cascade(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="Parent"))
    await task_service.upsert_task(
        data=TaskCreate(title="Child 1", parent_id=parent.id)
    )
    await task_service.upsert_task(
        data=TaskCreate(title="Child 2", parent_id=parent.id)
    )

    result = await task_service.delete_task(parent.id, cascade=True)
    assert result.deleted_count == 3


async def test_done_requires_children_done(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="Parent"))
    await task_service.upsert_task(
        data=TaskCreate(title="Child", parent_id=parent.id)
    )
    await task_service.upsert_task(
        update_data=TaskUpdate(status="in_progress"),
        task_id=parent.id,
    )

    with pytest.raises(AppError) as exc_info:
        await task_service.upsert_task(
            update_data=TaskUpdate(status="done"),
            task_id=parent.id,
        )
    assert exc_info.value.code == ErrorCode.PARENT_NOT_DONE


async def test_max_depth_exceeded(task_service: TaskService):
    ids = []
    for i in range(5):
        parent_id = ids[-1] if ids else None
        t = await task_service.upsert_task(
            data=TaskCreate(title=f"Level {i}", parent_id=parent_id)
        )
        ids.append(t.id)

    with pytest.raises(AppError) as exc_info:
        await task_service.upsert_task(
            data=TaskCreate(title="Too deep", parent_id=ids[-1])
        )
    assert exc_info.value.code == ErrorCode.MAX_DEPTH_EXCEEDED


async def test_decompose_task(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="Big task"))
    result = await task_service.decompose_task(
        parent.id,
        [
            SubTaskInput(title="Sub 1"),
            SubTaskInput(title="Sub 2", priority=1),
        ],
    )
    assert len(result.sub_tasks) == 2
    assert result.sub_tasks[0].parent_id == parent.id
    assert result.sub_tasks[1].priority == 1


async def test_thinking_process_stored(task_service: TaskService):
    result = await task_service.upsert_task(
        data=TaskCreate(title="Think task", thinking_process="AI thought about this")
    )
    assert result.meta_data.get("thinking") == "AI thought about this"


async def test_invalid_status(task_service: TaskService):
    with pytest.raises(AppError) as exc_info:
        await task_service.upsert_task(
            data=TaskCreate(title="Bad status", status="invalid")
        )
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


async def test_tags_filter(task_service: TaskService):
    await task_service.upsert_task(
        data=TaskCreate(title="Tagged", tags=["frontend", "urgent"])
    )
    await task_service.upsert_task(
        data=TaskCreate(title="Other", tags=["backend"])
    )

    result = await task_service.get_task_context(
        status_filter="all", tags=["frontend"]
    )
    assert all("frontend" in t.tags for t in result.tasks)


async def test_invalid_status_transition(task_service: TaskService):
    created = await task_service.upsert_task(data=TaskCreate(title="Transition"))

    with pytest.raises(AppError) as exc_info:
        await task_service.upsert_task(
            update_data=TaskUpdate(status="done"),
            task_id=created.id,
        )

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


async def test_blocked_can_resume_to_todo(task_service: TaskService):
    created = await task_service.upsert_task(
        data=TaskCreate(title="Blocked path", status="blocked")
    )

    updated = await task_service.upsert_task(
        update_data=TaskUpdate(status="todo"),
        task_id=created.id,
    )

    assert updated.status == "todo"


async def test_update_can_clear_nullable_fields(task_service: TaskService):
    created = await task_service.upsert_task(
        data=TaskCreate(
            title="Clear me",
            description="temporary",
            due_at="2026-04-10T10:00:00+00:00",
        )
    )

    updated = await task_service.upsert_task(
        update_data=TaskUpdate(description=None, due_at=None),
        task_id=created.id,
    )

    assert updated.description is None
    assert updated.due_at is None


async def test_update_can_remove_parent(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="Parent"))
    child = await task_service.upsert_task(
        data=TaskCreate(title="Child", parent_id=parent.id)
    )

    updated = await task_service.upsert_task(
        update_data=TaskUpdate(parent_id=None),
        task_id=child.id,
    )

    assert updated.parent_id is None


async def test_prevent_task_cycle(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="Parent"))
    child = await task_service.upsert_task(
        data=TaskCreate(title="Child", parent_id=parent.id)
    )

    with pytest.raises(AppError) as exc_info:
        await task_service.upsert_task(
            update_data=TaskUpdate(parent_id=child.id),
            task_id=parent.id,
        )

    assert exc_info.value.code == ErrorCode.TASK_CYCLE_DETECTED


async def test_keyword_search_matches_description(task_service: TaskService):
    await task_service.upsert_task(
        data=TaskCreate(title="Generic title", description="contains roadmap details")
    )

    result = await task_service.get_task_context(
        status_filter="all",
        query="roadmap",
    )

    assert result.total == 1
    assert result.tasks[0].title == "Generic title"


async def test_add_and_list_dependencies(task_service: TaskService):
    task = await task_service.upsert_task(data=TaskCreate(title="Task"))
    dependency = await task_service.upsert_task(data=TaskCreate(title="Dependency"))

    created = await task_service.add_dependency(task.id, dependency.id)
    listed = await task_service.list_dependencies(task.id)

    assert created.task_id == task.id
    assert created.depends_on_task_id == dependency.id
    assert len(listed.dependencies) == 1


async def test_prevent_dependency_cycle(task_service: TaskService):
    task_a = await task_service.upsert_task(data=TaskCreate(title="Task A"))
    task_b = await task_service.upsert_task(data=TaskCreate(title="Task B"))

    await task_service.add_dependency(task_a.id, task_b.id)

    with pytest.raises(AppError) as exc_info:
        await task_service.add_dependency(task_b.id, task_a.id)

    assert exc_info.value.code == ErrorCode.TASK_DEPENDENCY_CYCLE


async def test_ready_tasks_exclude_unfinished_dependencies(task_service: TaskService):
    blocked_task = await task_service.upsert_task(data=TaskCreate(title="Blocked", priority=1))
    dependency = await task_service.upsert_task(data=TaskCreate(title="Dependency"))
    ready_task = await task_service.upsert_task(data=TaskCreate(title="Ready", priority=2))

    await task_service.add_dependency(blocked_task.id, dependency.id)

    result = await task_service.list_ready_tasks()

    task_titles = [task.title for task in result.tasks]
    assert "Ready" in task_titles
    assert "Blocked" not in task_titles


async def test_done_requires_dependencies_done(task_service: TaskService):
    task = await task_service.upsert_task(data=TaskCreate(title="Task"))
    dependency = await task_service.upsert_task(data=TaskCreate(title="Dependency"))
    await task_service.add_dependency(task.id, dependency.id)
    await task_service.upsert_task(
        update_data=TaskUpdate(status="in_progress"),
        task_id=task.id,
    )

    with pytest.raises(AppError) as exc_info:
        await task_service.upsert_task(
            update_data=TaskUpdate(status="done"),
            task_id=task.id,
        )

    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


async def test_add_comment_and_list_timeline(task_service: TaskService):
    task = await task_service.upsert_task(data=TaskCreate(title="Task"))

    created = await task_service.add_comment(
        task.id,
        TaskCommentCreate(type="progress", content="Halfway there"),
    )
    timeline = await task_service.list_comments(task.id)

    assert created.type == "progress"
    assert any(item.content == "Halfway there" for item in timeline.comments)


async def test_task_events_are_recorded(task_service: TaskService):
    task = await task_service.upsert_task(data=TaskCreate(title="Task"))
    await task_service.upsert_task(
        update_data=TaskUpdate(status="in_progress"),
        task_id=task.id,
    )
    timeline = await task_service.list_comments(task.id)

    event_messages = [item.content for item in timeline.comments if item.type == "event"]
    assert any("Task created" in message for message in event_messages)
    assert any("Status changed" in message for message in event_messages)


async def test_workspace_views(task_service: TaskService):
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    today_task = await task_service.upsert_task(
        data=TaskCreate(title="Today", due_at=now.replace(hour=18, minute=0, second=0, microsecond=0))
    )
    await task_service.upsert_task(
        data=TaskCreate(title="Overdue", due_at=now - __import__("datetime").timedelta(days=1))
    )
    await task_service.upsert_task(
        data=TaskCreate(title="Blocked", status="blocked")
    )

    today = await task_service.list_today_tasks()
    overdue = await task_service.list_overdue_tasks()
    blocked = await task_service.list_blocked_tasks()
    alerts = await task_service.list_alerts()

    assert any(task.id == today_task.id for task in today.tasks)
    assert any(task.title == "Overdue" for task in overdue.tasks)
    assert any(task.title == "Blocked" for task in blocked.tasks)
    assert alerts.total >= 2


async def test_today_view_excludes_done_tasks(task_service: TaskService):
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    task = await task_service.upsert_task(
        data=TaskCreate(title="Done today", due_at=now)
    )
    await task_service.upsert_task(
        update_data=TaskUpdate(status="in_progress"),
        task_id=task.id,
    )
    await task_service.upsert_task(
        update_data=TaskUpdate(status="done"),
        task_id=task.id,
    )

    today = await task_service.list_today_tasks()
    assert all(item.id != task.id for item in today.tasks)


async def test_comment_api_disallows_event_type(task_service: TaskService):
    with pytest.raises(ValidationError):
        TaskCommentCreate(type="event", content="forged")


class FrozenDateTime(datetime):
    current: datetime = datetime(2026, 4, 5, 18, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


async def test_today_view_uses_configured_timezone(
    shanghai_task_service: TaskService,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(task_service_module, "datetime", FrozenDateTime)
    today_task = await shanghai_task_service.upsert_task(
        data=TaskCreate(
            title="Shanghai today",
            due_at=datetime(2026, 4, 6, 0, 30, tzinfo=timezone.utc),
        )
    )
    await shanghai_task_service.upsert_task(
        data=TaskCreate(
            title="Shanghai yesterday",
            due_at=datetime(2026, 4, 5, 15, 30, tzinfo=timezone.utc),
        )
    )

    shanghai_today = await shanghai_task_service.list_today_tasks()

    assert any(item.id == today_task.id for item in shanghai_today.tasks)
    assert all(item.title != "Shanghai yesterday" for item in shanghai_today.tasks)


async def test_overdue_view_uses_configured_timezone(
    shanghai_task_service: TaskService,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(task_service_module, "datetime", FrozenDateTime)
    task = await shanghai_task_service.upsert_task(
        data=TaskCreate(
            title="Shanghai overdue",
            due_at=datetime(2026, 4, 5, 17, 30, tzinfo=timezone.utc),
        )
    )

    overdue = await shanghai_task_service.list_overdue_tasks()

    assert any(item.id == task.id for item in overdue.tasks)
