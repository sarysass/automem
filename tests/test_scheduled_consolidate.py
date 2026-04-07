from __future__ import annotations

import importlib.util
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
        "user_id": None,
        "project_id": None,
    }


def test_build_payload_supports_scoped_env(monkeypatch: pytest.MonkeyPatch, scheduled_module):
    monkeypatch.setenv("MEMORY_CONSOLIDATE_USER_ID", "user-a")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_PROJECT_ID", "project-alpha")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_DRY_RUN", "true")
    monkeypatch.setenv("MEMORY_CONSOLIDATE_PRUNE_NON_WORK_ARCHIVED", "true")

    payload = scheduled_module.build_payload()

    assert payload["dry_run"] is True
    assert payload["normalize_task_state"] is True
    assert payload["prune_non_work_archived"] is True
    assert payload["user_id"] == "user-a"
    assert payload["project_id"] == "project-alpha"


def test_run_consolidation_rejects_non_200(scheduled_module):
    class FakeResponse:
        status_code = 500
        text = "boom"

        def json(self):
            return {"detail": "boom"}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/consolidate"
            assert json["dry_run"] is False
            return FakeResponse()

    with pytest.raises(RuntimeError, match="500"):
        scheduled_module.run_consolidation(FakeClient(), {"dry_run": False})


def test_run_consolidation_requires_expected_fields(scheduled_module):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"dry_run": False, "deleted_noise_count": 0}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            return FakeResponse()

    with pytest.raises(RuntimeError, match="missing expected keys"):
        scheduled_module.run_consolidation(FakeClient(), {"dry_run": False})
