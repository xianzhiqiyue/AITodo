import uuid

import pytest
import pytest_asyncio

from app.errors import AppError, ErrorCode
from app.schemas import SubTaskInput, TaskCreate, TaskUpdate
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
