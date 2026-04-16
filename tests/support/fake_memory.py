from __future__ import annotations

from typing import Any


class FakeMemory:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._next_id = 1

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
        memory_id = f"mem_{self._next_id}"
        self._next_id += 1
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
