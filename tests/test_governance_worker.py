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


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.requests: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, path: str, json: dict[str, object]):
        self.requests.append({"path": path, "json": json})
        return self.response


def test_run_once_calls_run_next_endpoint_when_processing_a_job(monkeypatch, worker_module):
    client = FakeClient(
        FakeResponse(
            {
                "status": "processed",
                "worker_id": "worker-a",
                "job": {"job_id": "job-42", "status": "completed"},
            }
        )
    )
    monkeypatch.setattr(worker_module, "build_client", lambda: client)

    result = worker_module.run_once(worker_id="worker-a")

    assert result == {
        "status": "processed",
        "worker_id": "worker-a",
        "job": {"job_id": "job-42", "status": "completed"},
    }
    assert client.requests == [
        {
            "path": "/v1/governance/jobs/run-next",
            "json": {"worker_id": "worker-a", "lease_seconds": 300},
        }
    ]


def test_run_once_returns_idle_when_run_next_is_idle(monkeypatch, worker_module):
    client = FakeClient(FakeResponse({"status": "idle", "worker_id": "worker-b"}))
    monkeypatch.setattr(worker_module, "build_client", lambda: client)

    result = worker_module.run_once(worker_id="worker-b")

    assert result == {"status": "idle", "worker_id": "worker-b"}
    assert client.requests == [
        {
            "path": "/v1/governance/jobs/run-next",
            "json": {"worker_id": "worker-b", "lease_seconds": 300},
        }
    ]


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
