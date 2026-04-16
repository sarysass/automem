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


# --- Task 1: sentinel payload protocol ---

def test_sentinel_payload_noisy_log_lines_ignored(tmp_path, monkeypatch) -> None:
    """Noisy JSON log lines outside sentinels should be ignored; only the sentinel block is parsed."""
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)
    begin = runtime_drivers.PAYLOAD_SENTINEL_BEGIN
    end = runtime_drivers.PAYLOAD_SENTINEL_END
    noisy_stdout = (
        'noise {"event":"heartbeat"}\n'
        f"{begin}\n"
        '{"status":"ok"}\n'
        f"{end}\n"
    )

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=noisy_stdout, stderr="")

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    result = runtime_drivers._run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=harness,
        env_overrides={"AUTOMEM_WORKER_ONCE": "true"},
    )
    assert result.payload == {"status": "ok"}


def test_sentinel_payload_pretty_printed_json(tmp_path, monkeypatch) -> None:
    """Multi-line indented JSON inside sentinels is parsed correctly."""
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)
    begin = runtime_drivers.PAYLOAD_SENTINEL_BEGIN
    end = runtime_drivers.PAYLOAD_SENTINEL_END
    import json
    body = json.dumps({"key": "value", "count": 42}, indent=2)
    pretty_stdout = f"{begin}\n{body}\n{end}\n"

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=pretty_stdout, stderr="")

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    result = runtime_drivers._run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=harness,
        env_overrides={"AUTOMEM_WORKER_ONCE": "true"},
    )
    assert result.payload == {"key": "value", "count": 42}


def test_sentinel_payload_no_sentinel_yields_none(tmp_path, monkeypatch) -> None:
    """Stdout with no sentinels yields payload=None regardless of other JSON lines."""
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0,
            stdout='{"looks": "like json but no sentinel"}\n',
            stderr=""
        )

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    result = runtime_drivers._run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=harness,
        env_overrides={"AUTOMEM_WORKER_ONCE": "true"},
    )
    assert result.payload is None


def test_sentinel_payload_json_array_returned_and_require_success_raises_distinct_error(tmp_path, monkeypatch) -> None:
    """JSON array inside sentinels is returned as list; require_success raises a distinct error about body not being dict."""
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)
    begin = runtime_drivers.PAYLOAD_SENTINEL_BEGIN
    end = runtime_drivers.PAYLOAD_SENTINEL_END
    array_stdout = f"{begin}\n[1, 2, 3]\n{end}\n"

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=array_stdout, stderr="")

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    result = runtime_drivers._run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=harness,
        env_overrides={"AUTOMEM_WORKER_ONCE": "true"},
    )
    assert result.payload == [1, 2, 3]

    with pytest.raises(RuntimeError, match="not a dict"):
        result.require_success()


def test_subprocess_run_uses_utf8_encoding(tmp_path, monkeypatch) -> None:
    """_run_runtime_script passes encoding='utf-8' to subprocess.run."""
    runtime_drivers = import_module("tests.support.runtime_drivers")
    harness = _make_live_backend(tmp_path)
    captured_kwargs: dict = {}

    begin = runtime_drivers.PAYLOAD_SENTINEL_BEGIN
    end = runtime_drivers.PAYLOAD_SENTINEL_END

    def fake_run(command, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            command, 0,
            stdout=f"{begin}\n" + '{"ok":true}\n' + f"{end}\n",
            stderr=""
        )

    monkeypatch.setattr(runtime_drivers.subprocess, "run", fake_run)

    runtime_drivers._run_runtime_script(
        "scripts/governance_worker.py",
        live_backend=harness,
        env_overrides={"AUTOMEM_WORKER_ONCE": "true"},
    )
    assert captured_kwargs.get("encoding") == "utf-8"
