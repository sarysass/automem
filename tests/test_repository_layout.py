from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def iter_repo_text_files() -> list[Path]:
    skip_dirs = {".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".ruff_cache"}
    allowed_suffixes = {
        ".md",
        ".py",
        ".ts",
        ".tsx",
        ".json",
        ".jsonc",
        ".toml",
        ".yml",
        ".yaml",
        ".txt",
        ".example",
    }
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.name in {"package-lock.json", "uv.lock"}:
            continue
        if path.suffix in allowed_suffixes or path.name.startswith(".env"):
            files.append(path)
    return files


def test_repository_includes_full_monorepo_layout() -> None:
    required_paths = [
        REPO_ROOT / "backend",
        REPO_ROOT / "cli",
        REPO_ROOT / "frontend",
        REPO_ROOT / "adapters",
        REPO_ROOT / "adapters/codex",
        REPO_ROOT / "adapters/openclaw",
        REPO_ROOT / "adapters/opencode",
        REPO_ROOT / "adapters/claude-code",
        REPO_ROOT / "docs/INTEGRATIONS.md",
        REPO_ROOT / "adapters/README.zh-CN.md",
        REPO_ROOT / "docs/INSTALLATION.md",
        REPO_ROOT / "docs/ARCHITECTURE.md",
        REPO_ROOT / "docs/NAMING.md",
        REPO_ROOT / "scripts/install_adapter.py",
        REPO_ROOT / ".github/workflows/ci.yml",
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required_paths if not path.exists()]
    assert missing == []


def test_repository_has_no_legacy_product_names_or_private_paths() -> None:
    forbidden_terms = [
        "memory" + "-hub",
        "memory" + "-platform",
        "/Users/" + "shali",
        "100.76" + ".210.36",
    ]
    allowed_docs = {
        "docs/NAMING.md",
    }
    offenders: list[str] = []
    for path in iter_repo_text_files():
        relative = str(path.relative_to(REPO_ROOT))
        if relative in allowed_docs:
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if any(term.lower() in lowered for term in forbidden_terms):
            offenders.append(relative)
    assert offenders == []


def test_adapter_metadata_uses_automem_names() -> None:
    manifests = [
        REPO_ROOT / "adapters/openclaw/openclaw.plugin.json",
        REPO_ROOT / "adapters/openclaw/package.json",
        REPO_ROOT / "adapters/opencode/package.json",
        REPO_ROOT / "adapters/claude-code/.claude-plugin/plugin.json",
    ]
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        joined = json.dumps(data, ensure_ascii=False).lower()
        assert "automem" in joined


def test_readme_describes_adapters_and_open_source_boundary() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "adapters/" in readme
    assert "可公开发布的完整项目仓库" in readme
    assert "不提交真实部署地址" in readme


def test_typescript_adapters_define_validation_scripts() -> None:
    manifests = [
        REPO_ROOT / "adapters/openclaw/package.json",
        REPO_ROOT / "adapters/opencode/package.json",
    ]
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        scripts = data.get("scripts") or {}
        assert "typecheck" in scripts
        assert "smoke" in scripts
