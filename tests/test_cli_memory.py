from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import json
import sys
from pathlib import Path


class DummyResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {"content-type": "application/json"}

    def json(self) -> dict[str, object]:
        return self._payload


class DummyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> "DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, path: str, json: dict[str, object] | None = None) -> DummyResponse:
        self.calls.append({"path": path, "json": json or {}})
        return DummyResponse({"ok": True})


def load_cli_module():
    module_path = Path(__file__).resolve().parents[1] / "cli" / "memory"
    loader = SourceFileLoader("automem_cli_memory", str(module_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, spec.name


def test_agent_key_create_forwards_bound_identity_fields(monkeypatch, capsys):
    module, module_name = load_cli_module()
    dummy_client = DummyClient()
    monkeypatch.setattr(module, "build_client", lambda: dummy_client)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "memory",
            "agent-key",
            "create",
            "--agent-id",
            "agent-phase04",
            "--label",
            "phase04 key",
            "--scopes",
            "task,search",
            "--user-id",
            "user-a",
            "--project-id",
            "project-alpha",
            "--project-id",
            "project-beta",
        ],
    )

    try:
        module.main()
    finally:
        sys.modules.pop(module_name, None)

    call = dummy_client.calls[0]
    assert call["path"] == "/agent-keys"
    assert call["json"] == {
        "agent_id": "agent-phase04",
        "label": "phase04 key",
        "scopes": ["task", "search"],
        "user_id": "user-a",
        "project_ids": ["project-alpha", "project-beta"],
    }
    assert json.loads(capsys.readouterr().out)["ok"] is True
