"""FakeMemory — a strict, deterministic test double for the mem0 Memory backend.

Contracts:
- `_extract_text` handles str, list-of-message-dicts (with str | list-of-parts | None content),
  and pydantic-style objects exposing a `.content` attribute.
- `None` content is empty string (tool/system turns that carry no text).
- A message dict missing the `content` key raises `TypeError` naming the missing key.
- Unknown message shapes raise `TypeError` rather than silently coercing to `str()`.
- All return paths yield deep copies so test-side mutation cannot corrupt the store.
- `add`, `search`, `get_all` accept only the kwargs production code actually uses.
- `get` and `delete` raise `FakeMemoryNotFound` on unknown ids.
"""
from __future__ import annotations

import copy
from typing import Any, Callable


class FakeMemoryNotFound(KeyError):
    """Raised by FakeMemory.get and FakeMemory.delete when the id is unknown."""


def _extract_parts(parts: list[Any]) -> str:
    """Join text parts from a list-of-parts content block; ignore non-text parts."""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            texts.append(part["text"])
    return "\n".join(texts)


def _extract_content(content: Any) -> str:
    """Extract text from the content field of a single message."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _extract_parts(content)
    raise TypeError(
        f"FakeMemory: unrecognised content shape {type(content).__name__!r}; "
        f"expected str, list-of-parts, or None"
    )


class FakeMemory:
    """Strict test double for the mem0 Memory backend.

    Optional constructor arguments:
    - clock: Callable[[], str] | None — injected ISO timestamp source.
      When None (default), all records use '2026-01-01T00:00:00+00:00'.
    - score_fn: Callable[[str, dict], float] | None — injected score function.
      Receives the search query and the record dict; returns a float score.
      When None (default), all matched records receive a score of 0.9.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        score_fn: Callable[[str, dict], float] | None = None,
    ) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self._clock = clock
        self._score_fn = score_fn

    def _now(self) -> str:
        if self._clock is not None:
            return self._clock()
        return "2026-01-01T00:00:00+00:00"

    def _score(self, query: str, record: dict[str, Any]) -> float:
        if self._score_fn is not None:
            return self._score_fn(query, record)
        return 0.9

    def _extract_text(self, messages: Any) -> str:
        """Extract a single string from the messages argument.

        Supports:
        - str — returned as-is.
        - list of message dicts — each dict must have a 'content' key whose
          value is str, list-of-parts ({"type":"text","text":"..."} items),
          or None. Missing 'content' key raises TypeError.
        - pydantic-style objects with a `.content` attribute.
        """
        if isinstance(messages, str):
            return messages
        if isinstance(messages, list):
            parts: list[str] = []
            for item in messages:
                if isinstance(item, dict):
                    if "content" not in item:
                        raise TypeError(
                            f"FakeMemory: message dict is missing required key 'content'; "
                            f"got keys: {sorted(item.keys())}"
                        )
                    text = _extract_content(item["content"])
                else:
                    # pydantic-style or other object with .content
                    if not hasattr(item, "content"):
                        raise TypeError(
                            f"FakeMemory: message item {type(item).__name__!r} has no 'content' attribute"
                        )
                    text = _extract_content(item.content)
                if text:
                    parts.append(text)
            return "\n".join(parts)
        raise TypeError(
            f"FakeMemory._extract_text: expected str or list, got {type(messages).__name__!r}"
        )

    def add(
        self,
        messages: Any,
        *,
        user_id: str | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        infer: bool = True,
        **_rejected: Any,
    ) -> dict[str, Any]:
        if _rejected:
            raise TypeError(
                f"FakeMemory.add received unexpected kwargs: {sorted(_rejected)}"
            )
        memory_id = f"mem_{self._next_id}"
        self._next_id += 1
        text = self._extract_text(messages)
        record: dict[str, Any] = {
            "id": memory_id,
            "memory": text,
            "text": text,
            "user_id": user_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "metadata": copy.deepcopy(metadata) if metadata is not None else {},
            "created_at": self._now(),
        }
        self.records[memory_id] = record
        return {"id": memory_id, "results": [copy.deepcopy(record)]}

    def get_all(
        self,
        *,
        user_id: str | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        **_rejected: Any,
    ) -> dict[str, Any]:
        if _rejected:
            raise TypeError(
                f"FakeMemory.get_all received unexpected kwargs: {sorted(_rejected)}"
            )
        results = list(self.records.values())
        for key, value in (("user_id", user_id), ("run_id", run_id), ("agent_id", agent_id)):
            if value is not None:
                results = [item for item in results if item.get(key) == value]
        return {"results": [copy.deepcopy(r) for r in results]}

    def search(
        self,
        query: str,
        *,
        user_id: str | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        filters: dict[str, Any] | None = None,
        **_rejected: Any,
    ) -> dict[str, Any]:
        if _rejected:
            raise TypeError(
                f"FakeMemory.search received unexpected kwargs: {sorted(_rejected)}"
            )
        query_lower = query.lower()
        results = list(self.records.values())
        for key, value in (("user_id", user_id), ("run_id", run_id), ("agent_id", agent_id)):
            if value is not None:
                results = [item for item in results if item.get(key) == value]
        if filters:
            filtered: list[dict[str, Any]] = []
            for item in results:
                metadata = item.get("metadata") or {}
                include = True
                for key, value in filters.items():
                    if metadata.get(key) != value:
                        include = False
                        break
                if include:
                    filtered.append(item)
            results = filtered
        matched = []
        for item in results:
            text = (item.get("memory") or item.get("text") or "").lower()
            if query_lower in text:
                matched.append({**copy.deepcopy(item), "score": self._score(query, item)})
        return {"results": matched}

    def get(self, memory_id: str) -> dict[str, Any]:
        if memory_id not in self.records:
            raise FakeMemoryNotFound(memory_id)
        return copy.deepcopy(self.records[memory_id])

    def delete(self, memory_id: str) -> None:
        if memory_id not in self.records:
            raise FakeMemoryNotFound(memory_id)
        del self.records[memory_id]
