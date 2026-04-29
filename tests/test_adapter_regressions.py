from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_claude_capture_commits_duplicate_state_only_after_success(tmp_path, monkeypatch):
    module = _load_module(
        f"automem_claude_common_{tmp_path.name}",
        REPO_ROOT / "adapters" / "claude-code" / "scripts" / "common.py",
    )
    cfg = module.RuntimeConfig(
        memory_url=None,
        memory_api_key=None,
        memory_user_id="user-a",
        memory_agent_id="claude-code",
        memory_project_id=None,
        cli_path=None,
        python_path=None,
        plugin_data_dir=tmp_path,
    )

    def failing_request(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_request_json", failing_request)
    try:
        module.capture_turn(
            cfg,
            message="please fix the regression",
            assistant_output="I changed the code.",
            explicit_long_term=False,
            task_like=True,
            session_id="session-1",
        )
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("capture_turn should propagate the failing capture")

    assert module.load_capture_state(cfg) == {}

    monkeypatch.setattr(module, "_request_json", lambda *_args, **_kwargs: {"route": "drop"})
    first = module.capture_turn(
        cfg,
        message="please fix the regression",
        assistant_output="I changed the code.",
        explicit_long_term=False,
        task_like=True,
        session_id="session-1",
    )
    assert first["route"] == "drop"

    duplicate = module.capture_turn(
        cfg,
        message="please fix the regression",
        assistant_output="I changed the code.",
        explicit_long_term=False,
        task_like=True,
        session_id="session-1",
    )
    assert duplicate == {"status": "skipped", "reason": "duplicate"}

    other_session = module.capture_turn(
        cfg,
        message="please fix the regression",
        assistant_output="I changed the code.",
        explicit_long_term=False,
        task_like=True,
        session_id="session-2",
    )
    assert other_session["route"] == "drop"


def test_codex_memory_store_restores_explicit_long_term_splitting(tmp_path, monkeypatch):
    class DummyFastMCP:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def tool(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def run(self):
            return None

    fake_mcp = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = DummyFastMCP
    fake_client_module = types.ModuleType("client")

    class DummyClient:
        def __init__(self) -> None:
            self.defaults = {
                "user_id": "default-user",
                "agent_id": "codex",
                "project_id": "automem-demo",
                "search_threshold": 0.3,
                "top_k": 6,
            }
            self.calls: list[dict[str, object]] = []

        def store(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "status": "stored",
                "results": [
                    {
                        "memory": kwargs["text"],
                        "metadata": kwargs["metadata"],
                    }
                ],
            }

    fake_client_module.AutomemClient = DummyClient
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)
    monkeypatch.setitem(sys.modules, "client", fake_client_module)

    module = _load_module(
        f"automem_codex_mcp_{tmp_path.name}",
        REPO_ROOT / "adapters" / "codex" / "mcp_server.py",
    )

    payload = module.memory_store(
        text="请记住：\n1. 我叫小李\n2. 公司是Example\n3. 偏好使用中文沟通",
        domain="long_term",
        user_id="user-a",
    )

    assert payload["stored_count"] == 3
    assert len(module.client.calls) == 3
    assert {call["text"] for call in module.client.calls} == {"姓名是小李", "公司是Example", "偏好使用中文沟通"}
    assert {call["metadata"]["category"] for call in module.client.calls} == {
        "user_profile",
        "project_context",
        "preference",
    }


def test_codex_lifespan_closes_http_client_on_shutdown(tmp_path, monkeypatch):
    class DummyFastMCP:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def tool(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def run(self):
            return None

    fake_mcp = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
    fake_fastmcp.FastMCP = DummyFastMCP
    fake_client_module = types.ModuleType("client")

    class DummyClient:
        def __init__(self) -> None:
            self.defaults = {
                "user_id": "default-user",
                "agent_id": "codex",
                "project_id": "automem-demo",
                "search_threshold": 0.3,
                "top_k": 6,
            }
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    fake_client_module.AutomemClient = DummyClient
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_mcp_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)
    monkeypatch.setitem(sys.modules, "client", fake_client_module)

    module = _load_module(
        f"automem_codex_lifespan_{tmp_path.name}",
        REPO_ROOT / "adapters" / "codex" / "mcp_server.py",
    )

    async def exercise_lifespan():
        async with module._client_lifespan(module.mcp):
            assert module.client.close_calls == 0

    asyncio.run(exercise_lifespan())

    assert module.mcp.kwargs["lifespan"] is module._client_lifespan
    assert module.client.close_calls == 1
