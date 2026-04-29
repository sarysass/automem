#!/usr/bin/env python3
from __future__ import annotations

import errno
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


EXPECTED_KEYS = {
    "dry_run",
    "duplicate_long_term_count",
    "canonicalized_long_term_count",
    "deleted_noise_count",
    "archived_tasks_count",
    "normalized_tasks_count",
    "task_reclassified_count",
}
EXPECTED_JOB_KEYS = {
    "job_id",
    "job_type",
    "status",
    "payload",
    "result",
    "attempts",
    "max_attempts",
}


def build_lock_path() -> Path:
    configured = os.environ.get("MEMORY_CONSOLIDATE_LOCK_FILE")
    if configured:
        return Path(configured)
    return Path(os.environ.get("TASK_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "tasks" / "tasks.db")).with_suffix(
        ".consolidate.lock"
    )


@contextmanager
def single_run_lock(lock_path: Path):
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


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_base_url() -> str:
    configured = os.environ.get("MEMORY_URL")
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    port = os.environ.get("BIND_PORT", "8888")
    return f"http://{host}:{port}"


def build_payload() -> dict[str, Any]:
    return {
        "dry_run": env_flag("MEMORY_CONSOLIDATE_DRY_RUN", False),
        "dedupe_long_term": env_flag("MEMORY_CONSOLIDATE_DEDUPE_LONG_TERM", True),
        "archive_closed_tasks": env_flag("MEMORY_CONSOLIDATE_ARCHIVE_CLOSED_TASKS", True),
        "normalize_task_state": env_flag("MEMORY_CONSOLIDATE_NORMALIZE_TASK_STATE", True),
        "prune_non_work_archived": env_flag("MEMORY_CONSOLIDATE_PRUNE_NON_WORK_ARCHIVED", False),
        "archive_work_without_memory_active": env_flag(
            "MEMORY_CONSOLIDATE_ARCHIVE_WORK_WITHOUT_MEMORY_ACTIVE",
            True,
        ),
        "prune_work_without_memory_archived": env_flag(
            "MEMORY_CONSOLIDATE_PRUNE_WORK_WITHOUT_MEMORY_ARCHIVED",
            False,
        ),
        "user_id": os.environ.get("MEMORY_CONSOLIDATE_USER_ID") or None,
        "project_id": os.environ.get("MEMORY_CONSOLIDATE_PROJECT_ID") or None,
    }


def build_mode() -> str:
    return (os.environ.get("MEMORY_CONSOLIDATE_MODE") or "enqueue").strip().lower()


def build_idempotency_key(payload: dict[str, Any]) -> str:
    explicit = os.environ.get("MEMORY_CONSOLIDATE_IDEMPOTENCY_KEY")
    if explicit:
        return explicit.strip()
    window_seconds = max(60, int(os.environ.get("MEMORY_CONSOLIDATE_IDEMPOTENCY_WINDOW_SECONDS", "3600")))
    bucket = int(time.time() // window_seconds)
    user_scope = payload.get("user_id") or "*"
    project_scope = payload.get("project_id") or "*"
    dry_run = "dry" if payload.get("dry_run") else "live"
    return f"consolidate:{user_scope}:{project_scope}:{dry_run}:bucket:{bucket}"


def build_job_request(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_type": "consolidate",
        "payload": payload,
        "user_id": payload.get("user_id"),
        "project_id": payload.get("project_id"),
        "idempotency_key": build_idempotency_key(payload),
        "max_attempts": max(1, int(os.environ.get("MEMORY_CONSOLIDATE_JOB_MAX_ATTEMPTS", "3"))),
    }


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


def validate_inline_result(data: dict[str, Any]) -> dict[str, Any]:
    missing = EXPECTED_KEYS - set(data.keys())
    if missing:
        raise RuntimeError(f"consolidate response missing expected keys: {sorted(missing)}")
    return data


def validate_job_result(data: dict[str, Any]) -> dict[str, Any]:
    missing = EXPECTED_JOB_KEYS - set(data.keys())
    if missing:
        raise RuntimeError(f"governance job response missing expected keys: {sorted(missing)}")
    return data


def run_consolidation(client: Any, payload: dict[str, Any]) -> dict[str, Any]:
    attempts = max(1, int(os.environ.get("MEMORY_CONSOLIDATE_ATTEMPTS", "3")))
    retry_delay = max(0.0, float(os.environ.get("MEMORY_CONSOLIDATE_RETRY_DELAY_SECONDS", "1")))
    mode = build_mode()
    if mode not in {"inline", "enqueue"}:
        raise RuntimeError(f"Unsupported MEMORY_CONSOLIDATE_MODE: {mode}")
    path = "/v1/consolidate" if mode == "inline" else "/v1/governance/jobs"
    body = payload if mode == "inline" else build_job_request(payload)
    last_error: RuntimeError | None = None
    for attempt in range(1, attempts + 1):
        response = client.post(path, json=body)
        if response.status_code == 200:
            data = response.json()
            return validate_inline_result(data) if mode == "inline" else validate_job_result(data)
        last_error = RuntimeError(
            f"{mode} consolidate failed with status {response.status_code}: {getattr(response, 'text', '')}"
        )
        if attempt < attempts:
            time.sleep(retry_delay)
    assert last_error is not None
    raise last_error


def main() -> int:
    load_runtime_env()
    payload = build_payload()
    with single_run_lock(build_lock_path()) as acquired:
        if not acquired:
            # Sentinel-wrapped so runtime_drivers can parse payload even on skipped path.
            # Source of truth for sentinel strings: tests/support/runtime_drivers.py
            print("===AUTOMEM_PAYLOAD_BEGIN===")
            print(json.dumps({"status": "skipped", "reason": "lock_exists"}, ensure_ascii=False))
            print("===AUTOMEM_PAYLOAD_END===")
            return 0
        with build_client() as client:
            result = run_consolidation(client, payload)
    # Sentinel-wrapped payload so runtime_drivers._parse_payload can locate it
    # regardless of log noise emitted before or after this block.
    # Source of truth for sentinel strings: tests/support/runtime_drivers.py
    print("===AUTOMEM_PAYLOAD_BEGIN===")
    print(json.dumps(result, ensure_ascii=False))
    print("===AUTOMEM_PAYLOAD_END===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
