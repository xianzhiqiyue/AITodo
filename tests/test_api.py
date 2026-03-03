import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


async def test_create_task_via_api(client: AsyncClient):
    resp = await client.post("/api/v1/tasks", json={
        "title": "API task",
        "priority": 1,
        "tags": ["test"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "API task"
    assert data["status"] == "todo"
    assert data["id"]


async def test_get_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "Get me"})
    task_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get me"


async def test_update_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "To update"})
    task_id = create_resp.json()["id"]

    resp = await client.put(f"/api/v1/tasks/{task_id}", json={
        "title": "Updated",
        "status": "in_progress",
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"
    assert resp.json()["status"] == "in_progress"


async def test_list_tasks_via_api(client: AsyncClient):
    await client.post("/api/v1/tasks", json={"title": "List item 1"})
    await client.post("/api/v1/tasks", json={"title": "List item 2"})

    resp = await client.get("/api/v1/tasks", params={"status_filter": "all"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    assert len(data["tasks"]) >= 2


async def test_delete_task_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "To delete"})
    task_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 1


async def test_decompose_via_api(client: AsyncClient):
    create_resp = await client.post("/api/v1/tasks", json={"title": "Big task"})
    task_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/tasks/{task_id}/decompose", json={
        "sub_tasks": [
            {"title": "Sub A"},
            {"title": "Sub B", "priority": 2},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sub_tasks"]) == 2


async def test_unauthorized(client: AsyncClient):
    async_client = client
    resp = await async_client.get(
        "/api/v1/tasks",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


async def test_missing_auth(client: AsyncClient):
    resp = await client.get(
        "/api/v1/tasks",
        headers={"Authorization": ""},
    )
    assert resp.status_code == 401


async def test_task_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"
