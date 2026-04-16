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


def test_run_once_posts_to_run_next(worker_module):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "idle", "worker_id": "worker-a"}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs/run-next"
            assert json["worker_id"] == "worker-a"
            return FakeResponse()

    result = worker_module.run_once(FakeClient(), worker_id="worker-a")

    assert result["status"] == "idle"


def test_main_skips_when_worker_lock_exists(
    monkeypatch: pytest.MonkeyPatch,
    worker_module,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
):
    lock_path = tmp_path / "worker.lock"
    lock_path.write_text("busy")

    monkeypatch.setenv("AUTOMEM_WORKER_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(worker_module, "load_runtime_env", lambda: None)

    class UnexpectedClient:
        def __enter__(self):
            raise AssertionError("client should not be created while lock exists")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(worker_module, "build_client", lambda: UnexpectedClient())

    exit_code = worker_module.main()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "skipped", "reason": "lock_exists"}
