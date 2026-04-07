import pytest

from app.schemas import TaskCreate
from app.services.task_planning_service import TaskPlanningService
from app.services.task_service import TaskService


pytestmark = pytest.mark.asyncio


async def test_apply_suggestions_creates_dependencies(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="发布项目版本"))
    planning_service = TaskPlanningService(task_service=task_service)

    result = await planning_service.apply_suggestions(parent.id, [0, 1, 2])

    assert len(result.sub_tasks) == 3
    second_dependencies = await task_service.list_dependencies(result.sub_tasks[1].id)
    third_dependencies = await task_service.list_dependencies(result.sub_tasks[2].id)

    assert second_dependencies.dependencies[0].depends_on_task_id == result.sub_tasks[0].id
    assert third_dependencies.dependencies[0].depends_on_task_id == result.sub_tasks[1].id


async def test_generate_plan_returns_goal_and_risks(task_service: TaskService):
    parent = await task_service.upsert_task(data=TaskCreate(title="发布项目版本"))
    planning_service = TaskPlanningService(task_service=task_service)

    plan = await planning_service.generate_plan(parent.id)

    assert plan.task_id == parent.id
    assert plan.goal == "发布项目版本"
    assert len(plan.suggestions) >= 3
