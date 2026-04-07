from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


class FakeMemory:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def _extract_text(self, messages: Any) -> str:
        if isinstance(messages, str):
            return messages
        if isinstance(messages, list):
            parts: list[str] = []
            for item in messages:
                if isinstance(item, dict):
                    parts.append(str(item.get("content", "")))
                else:
                    parts.append(str(getattr(item, "content", "")))
            return "\n".join(part for part in parts if part)
        return str(messages)

    def add(self, messages: Any, **params: Any) -> dict[str, Any]:
        memory_id = f"mem_{len(self.records) + 1}"
        text = self._extract_text(messages)
        record = {
            "id": memory_id,
            "memory": text,
            "text": text,
            "user_id": params.get("user_id"),
            "run_id": params.get("run_id"),
            "agent_id": params.get("agent_id"),
            "metadata": params.get("metadata") or {},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.records[memory_id] = record
        return {"id": memory_id, "results": [record]}

    def get_all(self, **params: Any) -> dict[str, Any]:
        results = list(self.records.values())
        for key in ("user_id", "run_id", "agent_id"):
            value = params.get(key)
            if value is not None:
                results = [item for item in results if item.get(key) == value]
        return {"results": results}

    def search(self, query: str, **params: Any) -> dict[str, Any]:
        query_lower = query.lower()
        results = list(self.records.values())
        for key in ("user_id", "run_id", "agent_id"):
            value = params.get(key)
            if value is not None:
                results = [item for item in results if item.get(key) == value]
        matched = []
        for item in results:
            text = (item.get("memory") or item.get("text") or "").lower()
            if query_lower in text:
                matched.append({**item, "score": 0.9})
        return {"results": matched}

    def get(self, memory_id: str) -> dict[str, Any]:
        return self.records[memory_id]

    def delete(self, memory_id: str) -> None:
        self.records.pop(memory_id, None)


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
