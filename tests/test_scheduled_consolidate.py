from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def scheduled_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "scheduled_consolidate.py"
    spec = importlib.util.spec_from_file_location("scheduled_consolidate_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_build_payload_defaults_to_full_cleanup(monkeypatch: pytest.MonkeyPatch, scheduled_module):
    monkeypatch.delenv("MEMORY_CONSOLIDATE_USER_ID", raising=False)
    monkeypatch.delenv("MEMORY_CONSOLIDATE_PROJECT_ID", raising=False)
    monkeypatch.delenv("MEMORY_CONSOLIDATE_DRY_RUN", raising=False)

    payload = scheduled_module.build_payload()

    assert payload == {
        "dry_run": False,
        "dedupe_long_term": True,
        "archive_closed_tasks": True,
        "normalize_task_state": True,
        "prune_non_work_archived": False,
        "archive_work_without_memory_active": True,
        "prune_work_without_memory_archived": False,
        "user_id": None,
        "project_id": None,
    }


def test_build_payload_supports_scoped_env(monkeypatch: pytest.MonkeyPatch, scheduled_module):
    monkeypatch.setenv("MEMORY_CONSOLIDATE_USER_ID", "user-a")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_PROJECT_ID", "project-alpha")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_DRY_RUN", "true")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_PRUNE_NON_WORK_ARCHIVED", "true")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_ARCHIVE_WORK_WITHOUT_MEMORY_ACTIVE", "false")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_PRUNE_WORK_WITHOUT_MEMORY_ARCHIVED", "true")

    payload = scheduled_module.build_payload()

    assert payload["dry_run"] is True
    assert payload["normalize_task_state"] is True
    assert payload["prune_non_work_archived"] is True
    assert payload["archive_work_without_memory_active"] is False
    assert payload["prune_work_without_memory_archived"] is True
    assert payload["user_id"] == "user-a"
    assert payload["project_id"] == "project-alpha"


def test_build_job_request_derives_bucketed_idempotency_key(monkeypatch: pytest.MonkeyPatch, scheduled_module):
    monkeypatch.setattr(scheduled_module.time, "time", lambda: 7200.0)
    job = scheduled_module.build_job_request(
        {
            "dry_run": False,
            "user_id": "user-a",
            "project_id": "project-alpha",
        }
    )

    assert job["job_type"] == "consolidate"
    assert job["idempotency_key"] == "consolidate:user-a:project-alpha:live:bucket:2"
    assert job["payload"]["project_id"] == "project-alpha"


def test_run_consolidation_rejects_non_200(scheduled_module):
    class FakeResponse:
        status_code = 500
        text = "boom"

        def json(self):
            return {"detail": "boom"}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs"
            assert json["payload"]["dry_run"] is False
            return FakeResponse()

    with pytest.raises(RuntimeError, match="500"):
        scheduled_module.run_consolidation(FakeClient(), {"dry_run": False})


def test_run_consolidation_retries_before_success(
    monkeypatch: pytest.MonkeyPatch, scheduled_module
):
    monkeypatch.setenv("MEMORY_CONSOLIDATE_ATTEMPTS", "2")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_RETRY_DELAY_SECONDS", "0")

    class FakeResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.text = "retry"

        def json(self):
            return {
                "job_id": "govjob_1",
                "job_type": "consolidate",
                "status": "pending",
                "payload": {"dry_run": False},
                "result": {},
                "attempts": 0,
                "max_attempts": 3,
            }

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def post(self, path: str, json: dict[str, object]):
            self.calls += 1
            return FakeResponse(500 if self.calls == 1 else 200)

    client = FakeClient()
    result = scheduled_module.run_consolidation(client, {"dry_run": False})

    assert client.calls == 2
    assert result["job_type"] == "consolidate"


def test_run_consolidation_requires_expected_fields(monkeypatch: pytest.MonkeyPatch, scheduled_module):
    monkeypatch.setenv("MEMORY_CONSOLIDATE_MODE", "inline")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"dry_run": False, "deleted_noise_count": 0}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/consolidate"
            return FakeResponse()

    with pytest.raises(RuntimeError, match="missing expected keys"):
        scheduled_module.run_consolidation(FakeClient(), {"dry_run": False})


def test_run_consolidation_enqueue_requires_expected_fields(scheduled_module):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"job_id": "govjob_1", "status": "pending"}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs"
            return FakeResponse()

    with pytest.raises(RuntimeError, match="governance job response missing expected keys"):
        scheduled_module.run_consolidation(FakeClient(), {"dry_run": False})


def test_main_skips_when_lock_exists(
    monkeypatch: pytest.MonkeyPatch, scheduled_module, capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    lock_path = tmp_path / "scheduled.lock"
    lock_path.write_text("busy")

    monkeypatch.setenv("MEMORY_CONSOLIDATE_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(scheduled_module, "load_runtime_env", lambda: None)
    monkeypatch.setattr(scheduled_module, "build_payload", lambda: {"dry_run": False})

    class UnexpectedClient:
        def __enter__(self):
            raise AssertionError("client should not be created while lock exists")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(scheduled_module, "build_client", lambda: UnexpectedClient())

    exit_code = scheduled_module.main()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"status": "skipped", "reason": "lock_exists"}
