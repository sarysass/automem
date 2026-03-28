from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "install_adapter.py"
SPEC = importlib.util.spec_from_file_location("install_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SUPPORTED_ADAPTERS = MODULE.SUPPORTED_ADAPTERS
install_adapter = MODULE.install_adapter


def test_install_adapter_copies_template_tree(tmp_path: Path) -> None:
    target = tmp_path / "codex"
    install_adapter("codex", target, force=False, copy_env_example=True)

    assert (target / "config.py").exists()
    assert (target / "client.py").exists()
    assert (target / "mcp_server.py").exists()
    assert (target / ".env.example").exists()
    assert (target / ".env").exists()


def test_install_adapter_force_replaces_existing_target(tmp_path: Path) -> None:
    target = tmp_path / "openclaw"
    target.mkdir()
    (target / "stale.txt").write_text("old", encoding="utf-8")

    install_adapter("openclaw", target, force=True, copy_env_example=False)

    assert not (target / "stale.txt").exists()
    assert (target / "index.ts").exists()
    assert (target / "package.json").exists()


def test_supported_adapters_are_backed_by_real_directories() -> None:
    missing = [name for name, path in SUPPORTED_ADAPTERS.items() if not path.exists()]
    assert missing == []
