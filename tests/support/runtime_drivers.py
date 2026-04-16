from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.support.live_backend import LiveBackendHarness, repo_root


@dataclass(frozen=True)
class RuntimeSubprocessResult:
    command: tuple[str, ...]
    env_overrides: dict[str, str]
    exit_code: int
    stdout: str
    stderr: str
    payload: dict[str, Any]

    def require_success(self) -> RuntimeSubprocessResult:
        if self.exit_code != 0:
            raise RuntimeError(
                f"Command {' '.join(self.command)} failed with exit code {self.exit_code}\n"
                f"stdout:\n{self.stdout}\n"
                f"stderr:\n{self.stderr}"
            )
        return self


def _base_runtime_env(live_backend: LiveBackendHarness) -> dict[str, str]:
    return {
        "MEMORY_URL": live_backend.base_url,
        "MEMORY_API_KEY": live_backend.admin_api_key,
        "ADMIN_API_KEY": live_backend.admin_api_key,
        "TASK_DB_PATH": str(live_backend.task_db_path),
        "HISTORY_DB_PATH": str(live_backend.history_db_path),
    }


def _new_lock_path(temp_dir: Path, stem: str) -> Path:
    return temp_dir / f"{stem}.{uuid.uuid4().hex}.lock"


def _parse_payload(command: tuple[str, ...], stdout: str, stderr: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        raise RuntimeError(
            f"Expected JSON object from {' '.join(command)}, received {type(parsed).__name__}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )
    raise RuntimeError(
        f"No JSON payload found in stdout from {' '.join(command)}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def _run_runtime_script(
    script_path: str,
    *,
    live_backend: LiveBackendHarness,
    env_overrides: Mapping[str, str],
) -> RuntimeSubprocessResult:
    command = ("uv", "run", "python", script_path)
    env = os.environ.copy()
    env.update(_base_runtime_env(live_backend))
    env.update(env_overrides)
    completed = subprocess.run(
        command,
        cwd=repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return RuntimeSubprocessResult(
        command=command,
        env_overrides=dict(env_overrides),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        payload=_parse_payload(command, completed.stdout, completed.stderr),
    )


def run_scheduler_enqueue(
    live_backend: LiveBackendHarness,
    *,
    idempotency_key: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> RuntimeSubprocessResult:
    env_overrides = {
        "MEMORY_CONSOLIDATE_MODE": "enqueue",
        "MEMORY_CONSOLIDATE_LOCK_FILE": str(_new_lock_path(live_backend.temp_dir, "runtime-scheduler")),
        "MEMORY_CONSOLIDATE_IDEMPOTENCY_KEY": idempotency_key or f"runtime-scheduler-{uuid.uuid4().hex}",
        "MEMORY_CONSOLIDATE_ATTEMPTS": "1",
        "MEMORY_CONSOLIDATE_RETRY_DELAY_SECONDS": "0",
    }
    if extra_env:
        env_overrides.update(extra_env)
    return _run_runtime_script(
        "scripts/scheduled_consolidate.py",
        live_backend=live_backend,
        env_overrides=env_overrides,
    )


def run_worker_once(
    live_backend: LiveBackendHarness,
    *,
    worker_id: str = "runtime-driver-worker",
    extra_env: Mapping[str, str] | None = None,
) -> RuntimeSubprocessResult:
    env_overrides = {
        "AUTOMEM_WORKER_ONCE": "true",
        "AUTOMEM_WORKER_ID": worker_id,
        "AUTOMEM_WORKER_LOCK_FILE": str(_new_lock_path(live_backend.temp_dir, "runtime-worker")),
    }
    if extra_env:
        env_overrides.update(extra_env)
    return _run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=live_backend,
        env_overrides=env_overrides,
    )
