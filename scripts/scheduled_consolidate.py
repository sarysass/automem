#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


EXPECTED_KEYS = {
    "dry_run",
    "duplicate_long_term_count",
    "canonicalized_long_term_count",
    "deleted_noise_count",
    "archived_tasks_count",
}


def load_runtime_env() -> None:
    explicit = os.environ.get("AUTOMEM_ENV_FILE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    candidates.extend(
        [
            repo_root / ".env",
            repo_root / "backend" / ".env",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate)


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_base_url() -> str:
    configured = os.environ.get("MEMORY_URL")
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    port = os.environ.get("BIND_PORT", "8888")
    return f"http://{host}:{port}"


def build_payload() -> dict[str, Any]:
    return {
        "dry_run": env_flag("MEMORY_CONSOLIDATE_DRY_RUN", False),
        "dedupe_long_term": env_flag("MEMORY_CONSOLIDATE_DEDUPE_LONG_TERM", True),
        "archive_closed_tasks": env_flag("MEMORY_CONSOLIDATE_ARCHIVE_CLOSED_TASKS", True),
        "user_id": os.environ.get("MEMORY_CONSOLIDATE_USER_ID") or None,
        "project_id": os.environ.get("MEMORY_CONSOLIDATE_PROJECT_ID") or None,
    }


def build_client() -> httpx.Client:
    api_key = os.environ.get("MEMORY_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing MEMORY_API_KEY or ADMIN_API_KEY")
    return httpx.Client(
        base_url=build_base_url(),
        headers={"X-API-Key": api_key},
        timeout=120.0,
        trust_env=False,
    )


def run_consolidation(client: Any, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/consolidate", json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"consolidate failed with status {response.status_code}: {getattr(response, 'text', '')}")
    data = response.json()
    missing = EXPECTED_KEYS - set(data.keys())
    if missing:
        raise RuntimeError(f"consolidate response missing expected keys: {sorted(missing)}")
    return data


def main() -> int:
    load_runtime_env()
    payload = build_payload()
    with build_client() as client:
        result = run_consolidation(client, payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
