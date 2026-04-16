#!/usr/bin/env python3
from __future__ import annotations

import errno
import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


def load_runtime_env() -> None:
    explicit = os.environ.get("AUTOMEM_ENV_FILE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    candidates.extend(
        [
            repo_root / ".env",
            repo_root / "backend" / ".env",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate)


def build_base_url() -> str:
    configured = os.environ.get("MEMORY_URL")
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    port = os.environ.get("BIND_PORT", "8888")
    return f"http://{host}:{port}"


def build_client() -> httpx.Client:
    api_key = os.environ.get("MEMORY_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing MEMORY_API_KEY or ADMIN_API_KEY")
    return httpx.Client(
        base_url=build_base_url(),
        headers={"X-API-Key": api_key},
        timeout=120.0,
        trust_env=False,
    )


def build_lock_path() -> Path:
    configured = os.environ.get("AUTOMEM_WORKER_LOCK_FILE")
    if configured:
        return Path(configured)
    return Path(os.environ.get("TASK_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "tasks" / "tasks.db")).with_suffix(
        ".worker.lock"
    )


@contextmanager
def single_worker_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        yield True
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
        yield False
    finally:
        if fd is not None:
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def build_worker_id() -> str:
    configured = os.environ.get("AUTOMEM_WORKER_ID")
    if configured:
        return configured.strip()
    return f"automem-worker@{socket.gethostname()}"


def run_once(client: Any, *, worker_id: str) -> dict[str, Any]:
    response = client.post(
        "/governance/jobs/run-next",
        json={
            "worker_id": worker_id,
            "lease_seconds": max(30, int(os.environ.get("AUTOMEM_WORKER_LEASE_SECONDS", "300"))),
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"governance worker failed with status {response.status_code}: {getattr(response, 'text', '')}")
    return response.json()


def main() -> int:
    load_runtime_env()
    poll_seconds = max(1.0, float(os.environ.get("AUTOMEM_WORKER_POLL_SECONDS", "5")))
    once = (os.environ.get("AUTOMEM_WORKER_ONCE") or "true").strip().lower() in {"1", "true", "yes", "on"}
    with single_worker_lock(build_lock_path()) as acquired:
        if not acquired:
            print(json.dumps({"status": "skipped", "reason": "lock_exists"}, ensure_ascii=False))
            return 0
        with build_client() as client:
            while True:
                result = run_once(client, worker_id=build_worker_id())
                print(json.dumps(result, ensure_ascii=False))
                if once or result.get("status") == "idle":
                    break
                time.sleep(poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
