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
