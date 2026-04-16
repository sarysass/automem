from __future__ import annotations

from importlib import import_module
import subprocess

import pytest

from tests.support.live_backend import LiveBackendHarness


def _make_live_backend(tmp_path) -> LiveBackendHarness:
    return LiveBackendHarness(
        base_url="http://127.0.0.1:9000",
        temp_dir=tmp_path,
        task_db_path=tmp_path / "tasks.db",
        history_db_path=tmp_path / "history.db",
        worker_lock_path=tmp_path / "worker.lock",
        consolidate_lock_path=tmp_path / "consolidate.lock",
        repo_task_db_path=tmp_path / "repo-tasks.db",
        admin_api_key="test-admin",
    )


def test_runtime_driver_returns_failure_context_without_json_payload(tmp_path, monkeypatch) -> None:
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)

    def fake_run(command, **kwargs):
        assert kwargs["timeout"] == runtime_drivers.RUNTIME_SCRIPT_TIMEOUT_SECONDS
        return subprocess.CompletedProcess(command, 2, stdout="plain failure\n", stderr="boom\n")

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    result = runtime_drivers._run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=harness,
        env_overrides={"AUTOMEM_WORKER_ONCE": "true"},
    )

    assert result.exit_code == 2
    assert result.payload is None
    assert result.stdout == "plain failure\n"
    assert result.stderr == "boom\n"


def test_runtime_driver_times_out_with_runtime_error(tmp_path, monkeypatch) -> None:
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=kwargs["timeout"],
            output="partial stdout\n",
            stderr="partial stderr\n",
        )

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out"):
        runtime_drivers._run_runtime_script(
            "scripts/scheduled_consolidate.py",
            live_backend=harness,
            env_overrides={"MEMORY_CONSOLIDATE_MODE": "enqueue"},
        )


def test_runtime_subprocess_result_requires_payload_for_success() -> None:
    runtime_drivers = import_module("tests.support.runtime_drivers")
    result = runtime_drivers.RuntimeSubprocessResult(
        command=("uv", "run", "python", "scripts/governance_worker.py"),
        env_overrides={},
        exit_code=0,
        stdout="no json here\n",
        stderr="",
        payload=None,
    )

    with pytest.raises(RuntimeError, match="without a JSON payload"):
        result.require_success()
