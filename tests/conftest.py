from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.support.fake_memory import FakeMemory


@pytest.fixture()
def backend_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module_path = Path(__file__).resolve().parents[1] / "backend" / "main.py"
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("ZAI_API_KEY", "test-zai-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("ZAI_MODEL", "glm-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    monkeypatch.setenv("QDRANT_PORT", "6333")
    monkeypatch.setenv("QDRANT_COLLECTION", "test-automem")
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))

    spec = importlib.util.spec_from_file_location(f"automem_backend_{tmp_path.name}", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MEMORY_BACKEND = FakeMemory()
    module.ensure_task_db()
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture()
def client(backend_module):
    with TestClient(backend_module.app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-admin"}
