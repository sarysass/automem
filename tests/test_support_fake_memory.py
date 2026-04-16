from __future__ import annotations

from importlib import import_module

import pytest


def test_fake_memory_support_matches_existing_crud_contract() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    added = memory.add(
        [{"role": "user", "content": "alpha record"}],
        user_id="user-1",
        run_id="run-1",
        agent_id="agent-1",
        metadata={"domain": "long_term"},
    )
    record = added["results"][0]

    assert added["id"] == "mem_1"
    assert record["memory"] == "alpha record"
    assert memory.get("mem_1") == record
    assert memory.get_all(user_id="user-1") == {"results": [record]}
    assert memory.search("alpha", user_id="user-1") == {"results": [{**record, "score": 0.9}]}

    memory.delete("mem_1")
    assert memory.get_all(user_id="user-1") == {"results": []}


def test_backend_module_uses_shared_fake_memory(backend_module) -> None:
    fake_memory_module = import_module("tests.support.fake_memory")

    assert isinstance(backend_module.MEMORY_BACKEND, fake_memory_module.FakeMemory)


def test_fake_memory_ids_do_not_get_reused_after_delete() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    first = memory.add("alpha")["id"]
    second = memory.add("beta")["id"]
    third = memory.add("gamma")["id"]

    memory.delete(second)
    replacement = memory.add("delta")

    assert first == "mem_1"
    assert second == "mem_2"
    assert third == "mem_3"
    assert replacement["id"] == "mem_4"
    assert memory.get("mem_3")["memory"] == "gamma"
    assert memory.get("mem_4")["memory"] == "delta"


# --- Task 2: faithful _extract_text ---

def test_extract_text_structured_content_stored_as_text() -> None:
    """Structured list-of-parts content is stored as plain text, not Python repr."""
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    added = memory.add(
        [{"role": "user", "content": [{"type": "text", "text": "alpha"}]}],
    )
    record = memory.get(added["id"])
    assert record["memory"] == "alpha"
    # Regression: must NOT produce Python repr of the list
    assert "[" not in record["memory"]
    assert "type" not in record["memory"]


def test_extract_text_none_content_yields_empty_string() -> None:
    """A message with content=None (e.g., tool turn) yields empty string and does not raise."""
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    added = memory.add(
        [{"role": "tool", "content": None}],
    )
    record = memory.get(added["id"])
    assert record["memory"] == ""


def test_extract_text_missing_content_key_raises_type_error() -> None:
    """A message dict without a 'content' key raises TypeError identifying the missing key."""
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    with pytest.raises(TypeError, match="content"):
        memory.add([{"role": "user"}])


def test_extract_text_non_text_parts_ignored() -> None:
    """Non-text parts (image_url, tool_use, etc.) are dropped; only text parts are joined."""
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    parts = [
        {"type": "text", "text": "a"},
        {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
        {"type": "text", "text": "b"},
    ]
    added = memory.add([{"role": "user", "content": parts}])
    record = memory.get(added["id"])
    assert record["memory"] == "a\nb"


# --- Task 3: strict FakeMemory contract with production-compatible kwargs ---


def test_search_accepts_backend_filters_kwarg() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    memory.add(
        [{"role": "user", "content": "偏好使用中文沟通"}],
        user_id="user-a",
        metadata={"domain": "long_term", "project_id": "project-a"},
    )
    memory.add(
        [{"role": "user", "content": "安排明天会议"}],
        user_id="user-a",
        metadata={"domain": "task", "project_id": "project-b"},
    )

    result = memory.search(
        "沟通",
        user_id="user-a",
        filters={"domain": "long_term", "project_id": "project-a"},
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["memory"] == "偏好使用中文沟通"
    assert result["results"][0]["metadata"]["project_id"] == "project-a"


def test_get_returns_defensive_copy_for_nested_metadata() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    added = memory.add(
        [{"role": "user", "content": "alpha"}],
        metadata={"status": "active", "nested": {"count": 1}},
    )
    record = memory.get(added["id"])
    record["metadata"]["status"] = "mutated"
    record["metadata"]["nested"]["count"] = 2

    reloaded = memory.get(added["id"])
    assert reloaded["metadata"]["status"] == "active"
    assert reloaded["metadata"]["nested"]["count"] == 1


def test_add_rejects_unexpected_kwargs() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    with pytest.raises(TypeError, match="unexpected kwargs"):
        memory.add("alpha", **{"user-id": "user-a"})


def test_injected_clock_controls_created_at() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    stamps = iter(["2026-02-01T00:00:00+00:00", "2026-02-01T00:00:01+00:00"])
    memory = fake_memory_module.FakeMemory(clock=lambda: next(stamps))

    first = memory.add("alpha")["results"][0]
    second = memory.add("beta")["results"][0]

    assert first["created_at"] == "2026-02-01T00:00:00+00:00"
    assert second["created_at"] == "2026-02-01T00:00:01+00:00"


def test_injected_score_fn_controls_search_scores() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory(
        score_fn=lambda query, record: 0.1 if record["memory"] == "alpha" else 0.8
    )

    memory.add("alpha")
    memory.add("beta")

    result = memory.search("a")
    by_memory = {item["memory"]: item["score"] for item in result["results"]}
    assert by_memory["alpha"] == 0.1
    assert by_memory["beta"] == 0.8


def test_get_and_delete_raise_fake_memory_not_found() -> None:
    fake_memory_module = import_module("tests.support.fake_memory")
    memory = fake_memory_module.FakeMemory()

    with pytest.raises(fake_memory_module.FakeMemoryNotFound):
        memory.get("missing")
    with pytest.raises(fake_memory_module.FakeMemoryNotFound):
        memory.delete("missing")
