"""API key (agent key) storage and bootstrap.

Owns the api_keys SQLite table operations: seed-from-JSON at startup,
create new keys, fetch + list. backend.main re-exports these functions
so adapters and tests using `from backend.main import create_agent_key`
keep working.

normalize_project_ids lives here too: it normalizes the project_ids
list that gets persisted into api_keys.project_ids_json. main.py also
calls it during scope enforcement on every request, hence the
re-export.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from typing import Any, Optional

from backend.storage import _resolve_task_db_path, ensure_task_db, hash_token, utcnow_iso


def normalize_project_ids(project_ids: Optional[Any]) -> list[str]:
    """Trim, dedupe, and stringify a project_ids iterable. Empty values dropped."""
    if not project_ids:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in project_ids:
        # Inlined normalize_text to avoid importing it from backend.main.
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def seed_agent_keys() -> None:
    """Bootstrap api_keys from AGENT_KEYS_JSON env var (idempotent INSERT OR IGNORE)."""
    ensure_task_db()
    raw = os.environ.get("AGENT_KEYS_JSON", "").strip()
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning("Failed to parse AGENT_KEYS_JSON; skipping agent key bootstrap")
        return
    if not isinstance(payload, list):
        logging.warning("AGENT_KEYS_JSON must be a list; skipping agent key bootstrap")
        return
    now = utcnow_iso()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        for item in payload:
            if not isinstance(item, dict):
                continue
            token = item.get("token")
            if not token:
                continue
            scopes = item.get("scopes") or []
            user_id = item.get("user_id")
            project_ids = normalize_project_ids(item.get("project_ids"))
            if "admin" not in scopes and not user_id:
                logging.warning(
                    "Skipping agent key bootstrap for %s because non-admin keys must declare user_id",
                    item.get("agent_id") or item.get("label") or "unknown",
                )
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO api_keys (key_id, token_hash, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    item.get("key_id") or f"key_{item.get('agent_id') or uuid.uuid4().hex[:8]}",
                    hash_token(str(token)),
                    item.get("label") or item.get("agent_id") or "agent",
                    item.get("agent_id"),
                    user_id,
                    json.dumps(project_ids, ensure_ascii=False),
                    json.dumps(scopes, ensure_ascii=False),
                    now,
                ),
            )
        conn.commit()


def create_agent_key(
    *,
    agent_id: str,
    label: str,
    scopes: list[str],
    user_id: Optional[str] = None,
    project_ids: Optional[list[str]] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    ensure_task_db()
    if "admin" not in scopes and not user_id:
        raise ValueError("Non-admin agent keys require user_id")
    normalized_project_ids = normalize_project_ids(project_ids)
    token_value = token or f"automem-agent-{uuid.uuid4().hex}"
    now = utcnow_iso()
    record = {
        "key_id": f"key_{agent_id}_{uuid.uuid4().hex[:8]}",
        "token": token_value,
        "label": label,
        "agent_id": agent_id,
        "user_id": user_id,
        "project_ids": normalized_project_ids,
        "scopes": scopes,
        "status": "active",
        "created_at": now,
    }
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO api_keys (key_id, token_hash, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                record["key_id"],
                hash_token(token_value),
                label,
                agent_id,
                user_id,
                json.dumps(normalized_project_ids, ensure_ascii=False),
                json.dumps(scopes, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
    return record


def fetch_api_key(token: str) -> Optional[dict[str, Any]]:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT key_id, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at, last_used_at FROM api_keys WHERE token_hash = ?",
            (hash_token(token),),
        ).fetchone()
    if not row:
        return None
    key = dict(row)
    key["project_ids"] = json.loads(key.pop("project_ids_json") or "[]")
    key["scopes"] = json.loads(key.pop("scopes_json") or "[]")
    return key


def list_api_keys() -> list[dict[str, Any]]:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key_id, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at, last_used_at FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    keys: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["project_ids"] = json.loads(item.pop("project_ids_json") or "[]")
        item["scopes"] = json.loads(item.pop("scopes_json") or "[]")
        keys.append(item)
    return keys


__all__ = [
    "create_agent_key",
    "fetch_api_key",
    "list_api_keys",
    "normalize_project_ids",
    "seed_agent_keys",
]
