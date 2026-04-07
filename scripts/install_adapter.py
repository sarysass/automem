#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTERS_DIR = REPO_ROOT / "adapters"
SUPPORTED_ADAPTERS = {
    "codex": ADAPTERS_DIR / "codex",
    "openclaw": ADAPTERS_DIR / "openclaw",
    "opencode": ADAPTERS_DIR / "opencode",
    "claude-code": ADAPTERS_DIR / "claude-code",
}
DEFAULT_TARGETS = {
    "codex": "~/.codex/automem-memory",
    "openclaw": "~/.openclaw/extensions/automem-memory",
    "opencode": "~/.config/opencode/plugins/automem",
    "claude-code": "~/.claude/plugins/automem-shared-memory",
}
SKIP_NAMES = {"node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install an automem adapter template into a target directory.")
    parser.add_argument("adapter", choices=sorted(SUPPORTED_ADAPTERS))
    parser.add_argument("--target", help="Install target directory. Defaults to the recommended user-level path.")
    parser.add_argument("--force", action="store_true", help="Replace the target directory if it already exists.")
    parser.add_argument(
        "--copy-env-example",
        action="store_true",
        help="Copy .env.example to .env when the adapter provides one and the target .env does not exist.",
    )
    return parser.parse_args()


def copy_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        if any(part in SKIP_NAMES for part in path.parts):
            continue
        relative = path.relative_to(src)
        target_path = dst / relative
        if path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target_path)


def install_adapter(adapter: str, target: Path, *, force: bool, copy_env_example: bool) -> None:
    source = SUPPORTED_ADAPTERS[adapter]
    preserved_env: str | None = None
    if target.exists():
        env_file = target / ".env"
        if env_file.exists():
            preserved_env = env_file.read_text(encoding="utf-8")
        if not force:
            raise FileExistsError(f"Target already exists: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    copy_tree(source, target)

    env_example = target / ".env.example"
    env_file = target / ".env"
    if preserved_env is not None and not env_file.exists():
        env_file.write_text(preserved_env, encoding="utf-8")
    if copy_env_example and env_example.exists() and not env_file.exists():
        shutil.copy2(env_example, env_file)


def main() -> int:
    args = parse_args()
    target = Path(args.target or DEFAULT_TARGETS[args.adapter]).expanduser()
    install_adapter(
        args.adapter,
        target,
        force=args.force,
        copy_env_example=args.copy_env_example,
    )
    print(f"Installed {args.adapter} adapter to {target}")
    if args.adapter in DEFAULT_TARGETS:
        print(f"Recommended default path: {Path(DEFAULT_TARGETS[args.adapter]).expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
