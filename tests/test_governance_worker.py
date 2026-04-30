from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def worker_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "governance_worker.py"
    spec = importlib.util.spec_from_file_location("governance_worker_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_run_once_dispatches_directly_when_a_job_is_claimed(monkeypatch, worker_module):
    seen: dict[str, object] = {}

    def fake_claim(*, worker_id, job_types, lease_seconds):
        seen["claim"] = {"worker_id": worker_id, "job_types": job_types, "lease_seconds": lease_seconds}
        return {"job_id": "job-42", "job_type": "consolidate"}

    def fake_dispatch(claimed, *, worker_id, memory_backend):
        seen["dispatch"] = {"claimed": claimed, "worker_id": worker_id, "memory_backend": memory_backend}
        return {"job_id": "job-42", "status": "completed"}

    def fake_get_memory_backend():
        return "fake-memory-backend"

    def fake_ensure_db():
        seen["ensure_db"] = True

    monkeypatch.setattr(
        worker_module,
        "_import_backend_dispatch",
        lambda: (fake_claim, fake_dispatch, fake_get_memory_backend, fake_ensure_db),
    )

    result = worker_module.run_once(worker_id="worker-a")

    assert result == {
        "status": "processed",
        "worker_id": "worker-a",
        "job": {"job_id": "job-42", "status": "completed"},
    }
    assert seen["ensure_db"] is True
    assert seen["claim"]["worker_id"] == "worker-a"
    assert seen["claim"]["job_types"] is None
    assert seen["claim"]["lease_seconds"] >= 30
    assert seen["dispatch"]["worker_id"] == "worker-a"
    assert seen["dispatch"]["memory_backend"] == "fake-memory-backend"


def test_run_once_returns_idle_when_no_job_claimed(monkeypatch, worker_module):
    monkeypatch.setattr(
        worker_module,
        "_import_backend_dispatch",
        lambda: (lambda **_kw: None, lambda *_args, **_kw: {}, lambda: None, lambda: None),
    )

    result = worker_module.run_once(worker_id="worker-b")

    assert result == {"status": "idle", "worker_id": "worker-b"}


def test_single_worker_lock_reclaims_stale_lock(monkeypatch: pytest.MonkeyPatch, worker_module, tmp_path: Path):
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text("999999", encoding="utf-8")

    def fake_kill(pid: int, sig: int):
        raise ProcessLookupError()

    monkeypatch.setattr(worker_module.os, "kill", fake_kill)

    with worker_module.single_worker_lock(lock_path) as acquired:
        assert acquired is True
        assert lock_path.read_text(encoding="utf-8").strip() == str(worker_module.os.getpid())

    assert not lock_path.exists()


def test_main_skips_when_worker_lock_exists(
    monkeypatch: pytest.MonkeyPatch,
    worker_module,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
):
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text("12345", encoding="utf-8")

    monkeypatch.setenv("AUTOMEM_WORKER_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(worker_module, "load_runtime_env", lambda: None)
    monkeypatch.setattr(worker_module, "_pid_is_alive", lambda pid: True)

    def explode():
        raise AssertionError("run_once should not be called while lock is held")

    monkeypatch.setattr(worker_module, "run_once", lambda **_kw: explode())

    exit_code = worker_module.main()

    assert exit_code == 0
    out = capsys.readouterr().out
    begin = "===AUTOMEM_PAYLOAD_BEGIN==="
    end = "===AUTOMEM_PAYLOAD_END==="
    lines = out.splitlines()
    body = "\n".join(lines[lines.index(begin) + 1 : lines.index(end)])
    assert json.loads(body) == {"status": "skipped", "reason": "lock_exists"}


def test_main_stays_alive_when_idle_in_service_mode(
    monkeypatch: pytest.MonkeyPatch,
    worker_module,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
):
    class StopLoop(Exception):
        pass

    lock_path = tmp_path / "worker.lock"
    monkeypatch.setenv("AUTOMEM_WORKER_LOCK_FILE", str(lock_path))
    monkeypatch.setenv("AUTOMEM_WORKER_ONCE", "false")
    monkeypatch.setenv("AUTOMEM_WORKER_POLL_SECONDS", "1")
    monkeypatch.setattr(worker_module, "load_runtime_env", lambda: None)

    calls = {"run_once": 0, "sleep": 0}

    def fake_run_once(*, worker_id: str):
        calls["run_once"] += 1
        return {"status": "idle", "worker_id": worker_id}

    def fake_sleep(seconds: float):
        calls["sleep"] += 1
        assert seconds == 1.0
        raise StopLoop()

    monkeypatch.setattr(worker_module, "run_once", fake_run_once)
    monkeypatch.setattr(worker_module.time, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        worker_module.main()

    assert calls == {"run_once": 1, "sleep": 1}
    assert capsys.readouterr().out == ""


def test_main_returns_error_code_when_run_once_raises(
    monkeypatch: pytest.MonkeyPatch,
    worker_module,
    tmp_path: Path,
):
    lock_path = tmp_path / "worker.lock"
    monkeypatch.setenv("AUTOMEM_WORKER_LOCK_FILE", str(lock_path))
    monkeypatch.setenv("AUTOMEM_WORKER_ONCE", "false")
    monkeypatch.setattr(worker_module, "load_runtime_env", lambda: None)

    def boom(**_kw):
        raise RuntimeError("backend dispatch crashed")

    monkeypatch.setattr(worker_module, "run_once", boom)

    exit_code = worker_module.main()

    assert exit_code == 1
    assert not lock_path.exists()
