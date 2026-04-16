from __future__ import annotations

import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tests.support.live_backend import LiveBackendHarness, repo_root

RUNTIME_SCRIPT_TIMEOUT_SECONDS = 60

# Sentinel markers that scripts must wrap their final JSON payload in.
# This prevents log-noise lines or pretty-printed JSON from accidentally
# being parsed as the business payload.
PAYLOAD_SENTINEL_BEGIN = "===AUTOMEM_PAYLOAD_BEGIN==="
PAYLOAD_SENTINEL_END = "===AUTOMEM_PAYLOAD_END==="


@dataclass(frozen=True)
class RuntimeSubprocessResult:
    command: tuple[str, ...]
    env_overrides: dict[str, str]
    exit_code: int
    stdout: str
    stderr: str
    payload: Any  # dict[str, Any] | list | scalar | None

    def require_success(self) -> RuntimeSubprocessResult:
        if self.exit_code != 0:
            raise RuntimeError(
                f"Command {' '.join(self.command)} failed with exit code {self.exit_code}\n"
                f"stdout:\n{self.stdout}\n"
                f"stderr:\n{self.stderr}"
            )
        if self.payload is None:
            raise RuntimeError(
                f"Command {' '.join(self.command)} succeeded without a JSON payload\n"
                f"stdout:\n{self.stdout}\n"
                f"stderr:\n{self.stderr}"
            )
        if not isinstance(self.payload, dict):
            raise RuntimeError(
                f"Command {' '.join(self.command)} returned a payload that is not a dict "
                f"(got {type(self.payload).__name__})\n"
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


def _default_lock_path(live_backend: LiveBackendHarness, stem: str) -> Path:
    """Return a stable lock path derived from live_backend.temp_dir and stem.

    Two calls with identical arguments return the same path, enabling
    single-flight and idempotent-replay behavior in tests without
    accidental lock collisions.
    """
    return live_backend.temp_dir / f"{stem}.lock"


def _unique_lock_path(temp_dir: Path, stem: str) -> Path:
    """Return a UUID-randomised lock path for tests that require per-call isolation."""
    return temp_dir / f"{stem}.{uuid.uuid4().hex}.lock"


def _parse_payload(command: tuple[str, ...], stdout: str, stderr: str) -> Any | None:
    """Extract the JSON payload from between sentinel markers in stdout.

    Returns the parsed JSON value (any type) if sentinels are found, or None
    if either sentinel is absent. Dict-ness is enforced at the call site
    (RuntimeSubprocessResult.require_success).
    """
    lines = stdout.splitlines()
    try:
        begin_idx = lines.index(PAYLOAD_SENTINEL_BEGIN)
    except ValueError:
        return None
    # Find the END sentinel after the BEGIN sentinel
    try:
        end_idx = lines.index(PAYLOAD_SENTINEL_END, begin_idx + 1)
    except ValueError:
        return None
    body = "\n".join(lines[begin_idx + 1 : end_idx])
    return json.loads(body)


# Allowlist of environment variables that are safe to pass to child processes.
# These are required for uv / Python / locale to work correctly.
# Do NOT add arbitrary developer variables here — the goal is to prevent local
# secrets or personalised shell settings from affecting slow-lane test outcomes.
RUNTIME_ENV_ALLOWLIST = frozenset({
    "PATH",       # required to locate uv and python
    "HOME",       # required by uv for cache / config lookups
    "LANG",       # required for locale-aware string handling
    "LC_ALL",     # required for locale-aware string handling
    "PYTHONPATH", # required when running tests from a source tree
    "VIRTUAL_ENV",  # required when an activated venv should be inherited
    "UV_CACHE_DIR",  # allows overriding the uv cache location in CI
})

# Contract keys that each runtime helper owns.  Callers must not override
# these via extra_env unless they pass allow_contract_override=True.
CONTRACT_KEYS_SCHEDULER = frozenset({
    "MEMORY_CONSOLIDATE_MODE",
    "MEMORY_CONSOLIDATE_ATTEMPTS",
    "MEMORY_CONSOLIDATE_RETRY_DELAY_SECONDS",
    "MEMORY_CONSOLIDATE_LOCK_FILE",
    "MEMORY_CONSOLIDATE_IDEMPOTENCY_KEY",
})

CONTRACT_KEYS_WORKER = frozenset({
    "AUTOMEM_WORKER_ONCE",
    "AUTOMEM_WORKER_ID",
    "AUTOMEM_WORKER_LOCK_FILE",
})

# Keys set by _base_runtime_env — also protected from extra_env override by default.
_BASE_ENV_KEYS = frozenset({
    "MEMORY_URL",
    "MEMORY_API_KEY",
    "ADMIN_API_KEY",
    "TASK_DB_PATH",
    "HISTORY_DB_PATH",
})


def _run_runtime_script(
    script_path: str,
    *,
    live_backend: LiveBackendHarness,
    env_overrides: Mapping[str, str],
) -> RuntimeSubprocessResult:
    command = ("uv", "run", "python", script_path)
    # Build env from allowlist only — do not inherit arbitrary developer env.
    env: dict[str, str] = {k: os.environ[k] for k in RUNTIME_ENV_ALLOWLIST if k in os.environ}
    env.update(_base_runtime_env(live_backend))
    env.update(env_overrides)
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root(),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=RUNTIME_SCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or exc.output or ""
        stderr = exc.stderr or ""
        raise RuntimeError(
            f"Command {' '.join(command)} timed out after {RUNTIME_SCRIPT_TIMEOUT_SECONDS}s\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        ) from exc

    payload = _parse_payload(command, completed.stdout, completed.stderr)
    return RuntimeSubprocessResult(
        command=command,
        env_overrides=dict(env_overrides),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        payload=payload,
    )


def run_scheduler_enqueue(
    live_backend: LiveBackendHarness,
    *,
    lock_path: Path | None = None,
    idempotency_key: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    allow_contract_override: bool = False,
) -> RuntimeSubprocessResult:
    resolved_lock = lock_path if lock_path is not None else _default_lock_path(live_backend, "runtime-scheduler")
    resolved_key = idempotency_key if idempotency_key is not None else "runtime-scheduler-default"
    env_overrides: dict[str, str] = {
        "MEMORY_CONSOLIDATE_MODE": "enqueue",
        "MEMORY_CONSOLIDATE_LOCK_FILE": str(resolved_lock),
        "MEMORY_CONSOLIDATE_IDEMPOTENCY_KEY": resolved_key,
        "MEMORY_CONSOLIDATE_ATTEMPTS": "1",
        "MEMORY_CONSOLIDATE_RETRY_DELAY_SECONDS": "0",
    }
    if extra_env:
        if not allow_contract_override:
            protected = CONTRACT_KEYS_SCHEDULER | _BASE_ENV_KEYS
            conflicts = sorted(protected & set(extra_env))
            if conflicts:
                raise ValueError(
                    f"run_scheduler_enqueue: extra_env contains contract keys that would "
                    f"override helper-controlled values: {conflicts}. "
                    f"Pass allow_contract_override=True to suppress this check."
                )
        env_overrides.update(extra_env)
    return _run_runtime_script(
        "scripts/scheduled_consolidate.py",
        live_backend=live_backend,
        env_overrides=env_overrides,
    )


def run_worker_once(
    live_backend: LiveBackendHarness,
    *,
    lock_path: Path | None = None,
    worker_id: str = "runtime-driver-worker",
    extra_env: Mapping[str, str] | None = None,
    allow_contract_override: bool = False,
) -> RuntimeSubprocessResult:
    resolved_lock = lock_path if lock_path is not None else _default_lock_path(live_backend, "runtime-worker")
    env_overrides: dict[str, str] = {
        "AUTOMEM_WORKER_ONCE": "true",
        "AUTOMEM_WORKER_ID": worker_id,
        "AUTOMEM_WORKER_LOCK_FILE": str(resolved_lock),
    }
    if extra_env:
        if not allow_contract_override:
            protected = CONTRACT_KEYS_WORKER | _BASE_ENV_KEYS
            conflicts = sorted(protected & set(extra_env))
            if conflicts:
                raise ValueError(
                    f"run_worker_once: extra_env contains contract keys that would "
                    f"override helper-controlled values: {conflicts}. "
                    f"Pass allow_contract_override=True to suppress this check."
                )
        env_overrides.update(extra_env)
    return _run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=live_backend,
        env_overrides=env_overrides,
    )
