from __future__ import annotations

from importlib import import_module

import httpx
import pytest


pytestmark = [pytest.mark.slow, pytest.mark.serial, pytest.mark.timeout(30)]


def test_live_backend_requires_api_key_over_real_http(tmp_path) -> None:
    live_backend_module = import_module("tests.support.live_backend")

    with live_backend_module.running_live_backend(tmp_path) as live_backend:
        response = httpx.get(live_backend.url("/healthz"), timeout=5.0, trust_env=False)

    assert response.status_code == 401
    assert response.json()["detail"] == "X-API-Key header is required"


def test_live_backend_healthz_uses_temp_runtime_state(tmp_path) -> None:
    live_backend_module = import_module("tests.support.live_backend")

    with live_backend_module.running_live_backend(tmp_path) as live_backend:
        response = httpx.get(
            live_backend.url("/healthz"),
            headers=live_backend.auth_headers,
            timeout=5.0,
            trust_env=False,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["task_db"] == str(live_backend.task_db_path)
    assert live_backend.task_db_path.parent == live_backend.temp_dir
    assert live_backend.history_db_path.parent == live_backend.temp_dir
    assert live_backend.worker_lock_path.parent == live_backend.temp_dir
    assert live_backend.consolidate_lock_path.parent == live_backend.temp_dir
    assert live_backend.task_db_path != live_backend.repo_task_db_path
