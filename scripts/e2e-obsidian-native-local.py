#!/usr/bin/env python3
"""Run a local end-to-end smoke for AITodo obsidian_native mode.

This helper orchestrates a local obsidianSync + AITodo smoke path:
1. starts isolated obsidianSync Postgres/MinIO Docker containers on non-default ports
2. runs obsidianSync migrations
3. starts obsidianSync sync-api
4. bootstraps/logs in admin and creates a Vault
5. creates a temporary SQLite AITodo database and starts AITodo in obsidian_native mode
6. runs scripts/smoke-obsidian-native.py with optional obsidianSync file verification

It is intended for local verification, not production deployment.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = ROOT.parent
OBSIDIAN_ROOT = CODE_ROOT / "obsidianSync"

OBSIDIAN_API_PORT = int(os.getenv("E2E_OBSIDIAN_API_PORT", "13000"))
AITODO_PORT = int(os.getenv("E2E_AITODO_PORT", "18000"))
POSTGRES_PORT = int(os.getenv("E2E_OBSIDIAN_POSTGRES_PORT", "15434"))
MINIO_PORT = int(os.getenv("E2E_OBSIDIAN_MINIO_PORT", "19002"))
MINIO_CONSOLE_PORT = int(os.getenv("E2E_OBSIDIAN_MINIO_CONSOLE_PORT", "19003"))

JWT_SECRET = os.getenv("E2E_OBSIDIAN_JWT_SECRET", "test-jwt-secret-change-me-32chars")
ADMIN_EMAIL = os.getenv("E2E_OBSIDIAN_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("E2E_OBSIDIAN_ADMIN_PASSWORD", "admin123456")
VAULT_NAME = os.getenv("E2E_OBSIDIAN_VAULT_NAME", f"AITodo-E2E-{int(time.time())}")


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), f"(cwd={cwd})")
    return subprocess.run(cmd, cwd=cwd, env=env, check=check)


def wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def wait_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {host}:{port}")



def wait_postgres_container(container: str, database: str = "obsidian_sync", timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    last: subprocess.CompletedProcess | None = None
    while time.time() < deadline:
        last = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", database],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if last.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for postgres container {container}")

def http_json(method: str, url: str, payload: dict[str, Any] | None = None, token: str | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def terminate(proc: subprocess.Popen | None, name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    print(f"Stopping {name} pid={proc.pid}")
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main() -> int:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(__doc__.strip())
        return 0
    if not OBSIDIAN_ROOT.exists():
        raise SystemExit(f"Missing sibling obsidianSync repo: {OBSIDIAN_ROOT}")
    if shutil.which("docker") is None:
        raise SystemExit("docker is required")

    obsidian_api: subprocess.Popen | None = None
    aitodo_api: subprocess.Popen | None = None
    run_id = str(int(time.time()))
    postgres_container = f"aitodo-e2e-postgres-{run_id}"
    minio_container = f"aitodo-e2e-minio-{run_id}"
    temp_dir = Path(tempfile.mkdtemp(prefix="aitodo-obsidian-e2e-"))
    sqlite_path = temp_dir / "aitodo-e2e.db"
    obsidian_base = f"http://127.0.0.1:{OBSIDIAN_API_PORT}/api/v1"
    aitodo_base = f"http://127.0.0.1:{AITODO_PORT}"

    obsidian_env = os.environ.copy()
    obsidian_env.update({
        "APP_ENV": "development",
        "HOST": "127.0.0.1",
        "PORT": str(OBSIDIAN_API_PORT),
        "BASE_URL": f"http://127.0.0.1:{OBSIDIAN_API_PORT}",
        "POSTGRES_DSN": f"postgres://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/obsidian_sync",
        "JWT_SECRET": JWT_SECRET,
        "S3_ENDPOINT": f"http://127.0.0.1:{MINIO_PORT}",
        "S3_BUCKET": "obsidian-sync",
        "S3_ACCESS_KEY": "minioadmin",
        "S3_SECRET_KEY": "minioadmin",
        "S3_FORCE_PATH_STYLE": "true",
        "SEED_ADMIN_EMAIL": ADMIN_EMAIL,
        "SEED_ADMIN_PASSWORD": ADMIN_PASSWORD,
    })

    try:
        print("[1/8] Starting isolated obsidianSync infra")
        run(["docker", "rm", "-f", postgres_container], cwd=ROOT, check=False)
        run(["docker", "rm", "-f", minio_container], cwd=ROOT, check=False)
        run([
            "docker", "run", "--rm", "-d",
            "--name", postgres_container,
            "-e", "POSTGRES_PASSWORD=postgres",
            "-e", "POSTGRES_DB=obsidian_sync",
            "-p", f"127.0.0.1:{POSTGRES_PORT}:5432",
            "postgres:16-alpine",
        ], cwd=ROOT)
        run([
            "docker", "run", "--rm", "-d",
            "--name", minio_container,
            "-e", "MINIO_ROOT_USER=minioadmin",
            "-e", "MINIO_ROOT_PASSWORD=minioadmin",
            "-p", f"127.0.0.1:{MINIO_PORT}:9000",
            "-p", f"127.0.0.1:{MINIO_CONSOLE_PORT}:9001",
            "minio/minio:latest", "server", "/data", "--console-address", ":9001",
        ], cwd=ROOT)
        wait_port("127.0.0.1", POSTGRES_PORT)
        wait_postgres_container(postgres_container)
        wait_port("127.0.0.1", MINIO_PORT)

        print("[2/8] Migrating obsidianSync")
        run(["npm", "run", "--workspace", "@obsidian-sync/sync-api", "migrate"], cwd=OBSIDIAN_ROOT, env=obsidian_env)

        print("[3/8] Starting obsidianSync API")
        obsidian_api = subprocess.Popen(["npm", "exec", "--workspace", "@obsidian-sync/sync-api", "--", "tsx", "src/index.ts"], cwd=OBSIDIAN_ROOT, env=obsidian_env)
        wait_http(f"{obsidian_base}/health")
        wait_http(f"{obsidian_base}/ready", timeout=45)

        print("[4/8] Login and create Vault")
        login = http_json("POST", f"{obsidian_base}/auth/login", {
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "deviceName": "AITodo-E2E",
            "platform": "linux",
            "pluginVersion": "e2e",
        })
        token = login["accessToken"]
        vault = http_json("POST", f"{obsidian_base}/vaults", {"name": VAULT_NAME}, token=token)
        vault_id = vault["vaultId"]
        print(f"  vault_id={vault_id}")

        print("[5/8] Migrating AITodo temp DB")
        aitodo_env = os.environ.copy()
        aitodo_env.update({
            "DATABASE_URL": f"sqlite+aiosqlite:///{sqlite_path}",
            "API_KEY": "e2e-key",
            "AITODO_STORAGE_MODE": "obsidian_native",
            "OBSIDIAN_SYNC_BASE_URL": obsidian_base,
            "OBSIDIAN_SYNC_ACCESS_TOKEN": token,
            "OBSIDIAN_SYNC_VAULT_ID": vault_id,
            "LOG_LEVEL": "WARNING",
        })
        run([str(ROOT / ".venv/bin/python"), "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=aitodo_env)

        print("[6/8] Starting AITodo API")
        aitodo_api = subprocess.Popen([
            str(ROOT / ".venv/bin/python"),
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(AITODO_PORT),
        ], cwd=ROOT, env=aitodo_env)
        wait_http(f"{aitodo_base}/health")

        print("[7/8] Running smoke")
        smoke_env = os.environ.copy()
        smoke_env.update({
            "AITODO_BASE_URL": aitodo_base,
            "API_KEY": "e2e-key",
            "OBSIDIAN_SYNC_BASE_URL": obsidian_base,
            "OBSIDIAN_SYNC_ACCESS_TOKEN": token,
            "OBSIDIAN_SYNC_VAULT_ID": vault_id,
        })
        run([str(ROOT / "scripts/smoke-obsidian-native.py")], cwd=ROOT, env=smoke_env)

        print("[8/8] E2E OK")
        return 0
    finally:
        terminate(aitodo_api, "AITodo API")
        terminate(obsidian_api, "obsidianSync API")
        if os.getenv("E2E_KEEP_INFRA") != "1":
            run(["docker", "rm", "-f", postgres_container], cwd=ROOT, check=False)
            run(["docker", "rm", "-f", minio_container], cwd=ROOT, check=False)
        else:
            print(f"Keeping infra containers: {postgres_container}, {minio_container}")
        if os.getenv("E2E_KEEP_TMP") != "1":
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
