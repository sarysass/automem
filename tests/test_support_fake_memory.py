from __future__ import annotations

from importlib import import_module


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
