#!/usr/bin/env python3
"""Smoke test for AITodo obsidian_native mode.

This script exercises the AITodo REST API end-to-end:
1. parse-and-create a task
2. add a timeline comment
3. generate a plan
4. apply part of the plan as Obsidian-native subtasks
5. read dashboard
6. optionally verify the created Markdown file through obsidianSync files API

Required env:
  API_KEY or AITODO_API_KEY
Optional env:
  AITODO_BASE_URL (default: http://127.0.0.1:8000)
  SMOKE_TASK_TEXT
  OBSIDIAN_SYNC_BASE_URL
  OBSIDIAN_SYNC_ACCESS_TOKEN
  OBSIDIAN_SYNC_VAULT_ID
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@dataclass
class HttpClient:
    base_url: str
    token: str | None = None

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> Any:
        url = self.base_url.rstrip("/") + path
        if query:
            url += "?" + urlencode(query, doseq=True)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=20) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def require_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    joined = " or ".join(names)
    raise SystemExit(f"Missing required env: {joined}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(__doc__.strip())
        return 0
    base_url = os.getenv("AITODO_BASE_URL", "http://127.0.0.1:8000")
    api_key = require_env("AITODO_API_KEY", "API_KEY")
    task_text = os.getenv("SMOKE_TASK_TEXT", f"Obsidian native smoke test {int(time.time())}，补充联调验证")
    client = HttpClient(base_url=base_url, token=api_key)

    print(f"[1/6] parse-and-create via {base_url}")
    created = client.request(
        "POST",
        "/api/v1/tasks/parse-and-create",
        {
            "text": task_text,
            "force_create": True,
            "override": {"tags": ["smoke", "obsidian-native"]},
        },
    )
    assert_true(created.get("created") is True, "parse-and-create did not create a task")
    task = created.get("task") or {}
    task_id = task.get("id")
    assert_true(bool(task_id), "created task id missing")
    assert_true(task.get("meta_data", {}).get("source") == "obsidian_native_index", "task is not from obsidian_native_index")
    print(f"  created task: {task_id} path={task.get('meta_data', {}).get('path')}")

    print("[2/6] add comment and verify timeline")
    comment = client.request(
        "POST",
        f"/api/v1/tasks/{task_id}/comments",
        {"type": "progress", "content": "smoke: native timeline ok", "meta_data": {"smoke": True}},
    )
    assert_true(comment.get("content") == "smoke: native timeline ok", "comment response mismatch")
    timeline = client.request("GET", f"/api/v1/tasks/{task_id}/timeline")
    assert_true(any(item.get("content") == "smoke: native timeline ok" for item in timeline.get("comments", [])), "timeline missing smoke comment")

    print("[3/6] generate plan")
    plan = client.request("POST", f"/api/v1/tasks/{task_id}/plan")
    suggestions = plan.get("suggestions", [])
    assert_true(len(suggestions) >= 1, "plan suggestions missing")
    print(f"  suggestions: {len(suggestions)}")

    print("[4/6] apply first plan item")
    applied = client.request("POST", f"/api/v1/tasks/{task_id}/apply-plan", {"indices": [0]})
    sub_tasks = applied.get("sub_tasks", [])
    assert_true(len(sub_tasks) == 1, "apply-plan did not create exactly one subtask")
    assert_true(sub_tasks[0].get("parent_id") == task_id, "subtask parent_id mismatch")
    print(f"  subtask: {sub_tasks[0].get('id')}")

    print("[5/6] dashboard")
    dashboard = client.request("GET", "/api/v1/workspace/dashboard", query={"top_n": 10})
    assert_true("ready_to_start" in dashboard, "dashboard missing ready_to_start")
    assert_true("suggested_today" in dashboard, "dashboard missing suggested_today")

    print("[6/6] optional obsidianSync file verification")
    sync_base = os.getenv("OBSIDIAN_SYNC_BASE_URL")
    sync_token = os.getenv("OBSIDIAN_SYNC_ACCESS_TOKEN")
    vault_id = os.getenv("OBSIDIAN_SYNC_VAULT_ID")
    path = task.get("meta_data", {}).get("path")
    if sync_base and sync_token and vault_id and path:
        sync = HttpClient(base_url=sync_base, token=sync_token)
        remote = sync.request("GET", f"/vaults/{vault_id}/files/by-path/{quote(path, safe='')}")
        assert_true(remote.get("file", {}).get("path") == path, "obsidianSync file path mismatch")
        print(f"  obsidianSync verified fileId={remote.get('file', {}).get('fileId')}")
    else:
        print("  skipped (set OBSIDIAN_SYNC_BASE_URL, OBSIDIAN_SYNC_ACCESS_TOKEN, OBSIDIAN_SYNC_VAULT_ID to enable)")

    print("SMOKE OK")
    print(json.dumps({"task_id": task_id, "sub_task_id": sub_tasks[0].get("id")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SMOKE FAILED: {exc}", file=sys.stderr)
        raise
