"""HTTP authentication + scope enforcement for automem.

Centralizes the X-API-Key header dependency, the api_keys table lookup
on every authenticated request, and the cross-cutting scope/identity
checks (require_scope, enforce_agent_identity, enforce_user_identity,
enforce_project_identity).

Env-driven values (ADMIN_API_KEY, AUTOMEM_ALLOW_INSECURE_NOAUTH) are
read at call time rather than import time so per-test importlib reloads
in conftest pick up the latest monkeypatched values. Same pattern as
backend.storage._resolve_task_db_path.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from typing import Any, Optional

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from backend.agent_keys import fetch_api_key, normalize_project_ids
from backend.storage import _resolve_task_db_path, ensure_task_db, utcnow_iso


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


_TRUTHY = {"1", "true", "yes", "on"}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _admin_api_key() -> str:
    return os.environ.get("ADMIN_API_KEY", "")


def _allow_insecure_noauth() -> bool:
    return os.environ.get("AUTOMEM_ALLOW_INSECURE_NOAUTH", "").strip().lower() in _TRUTHY


def auth_bootstrap_bypass_enabled() -> bool:
    return _allow_insecure_noauth() or "PYTEST_CURRENT_TEST" in os.environ


def has_usable_api_keys() -> bool:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM api_keys
            WHERE status = 'active'
              AND (
                COALESCE(user_id, '') != ''
                OR scopes_json LIKE '%"admin"%'
              )
            LIMIT 1
            """
        ).fetchone()
    return row is not None


def touch_api_key(key_id: str) -> None:
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
            (utcnow_iso(), key_id),
        )
        conn.commit()


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)) -> dict[str, Any]:
    if api_key is None:
        raise HTTPException(status_code=401, detail="X-API-Key header is required")
    admin_key = _admin_api_key()
    if admin_key and secrets.compare_digest(api_key, admin_key):
        return {
            "actor_type": "admin",
            "actor_label": "admin",
            "agent_id": None,
            "scopes": ["admin"],
            "is_admin": True,
        }
    key = fetch_api_key(api_key)
    if not key or key.get("status") != "active":
        raise HTTPException(status_code=401, detail="Invalid API key")
    touch_api_key(key["key_id"])
    scopes = key.get("scopes") or []
    is_admin = "admin" in scopes
    if not is_admin and not key.get("user_id"):
        raise HTTPException(status_code=403, detail="Non-admin API keys must be bound to a user_id")
    return {
        "actor_type": "agent_key",
        "actor_label": key.get("label"),
        "agent_id": key.get("agent_id"),
        "user_id": key.get("user_id"),
        "project_ids": key.get("project_ids") or [],
        "scopes": scopes,
        "is_admin": is_admin,
    }


def require_scope(auth: dict[str, Any], scope: str) -> None:
    if auth.get("is_admin"):
        return
    scopes = set(auth.get("scopes") or [])
    if scope not in scopes and "admin" not in scopes:
        raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")


def enforce_agent_identity(auth: dict[str, Any], agent_id: Optional[str]) -> Optional[str]:
    if auth.get("is_admin"):
        return agent_id
    key_agent_id = auth.get("agent_id")
    if agent_id and key_agent_id and agent_id != key_agent_id:
        raise HTTPException(status_code=403, detail="agent_id does not match API key identity")
    return key_agent_id or agent_id


def enforce_user_identity(auth: dict[str, Any], user_id: Optional[str]) -> Optional[str]:
    if auth.get("is_admin"):
        return user_id
    key_user_id = auth.get("user_id")
    if not key_user_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a user_id")
    if user_id and key_user_id and user_id != key_user_id:
        raise HTTPException(status_code=403, detail="user_id does not match API key identity")
    return key_user_id or user_id


def enforce_project_identity(auth: dict[str, Any], project_id: Optional[str]) -> Optional[str]:
    if auth.get("is_admin"):
        return project_id
    allowed_project_ids = normalize_project_ids(auth.get("project_ids"))
    if not allowed_project_ids:
        return project_id
    if project_id:
        if project_id not in allowed_project_ids:
            raise HTTPException(status_code=403, detail="project_id does not match API key access scope")
        return project_id
    if len(allowed_project_ids) == 1:
        return allowed_project_ids[0]
    raise HTTPException(status_code=400, detail="project_id is required for API keys bound to multiple projects")


def enforce_payload_project_identity(auth: dict[str, Any], payload: Any) -> None:
    if not hasattr(payload, "project_id"):
        return
    payload.project_id = enforce_project_identity(auth, getattr(payload, "project_id"))


def merge_project_id_into_metadata(project_id: Optional[str], metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(metadata or {})
    existing = _normalize_text(str(merged.get("project_id") or ""))
    if project_id and existing and existing != project_id:
        raise HTTPException(status_code=400, detail="project_id conflicts with metadata.project_id")
    if project_id:
        merged["project_id"] = project_id
    return merged


def merge_project_id_into_filters(project_id: Optional[str], filters: Optional[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(filters or {})
    existing = _normalize_text(str(merged.get("project_id") or ""))
    if project_id and existing and existing != project_id:
        raise HTTPException(status_code=400, detail="project_id conflicts with filters.project_id")
    if project_id:
        merged["project_id"] = project_id
    return merged


__all__ = [
    "api_key_header",
    "auth_bootstrap_bypass_enabled",
    "enforce_agent_identity",
    "enforce_payload_project_identity",
    "enforce_project_identity",
    "enforce_user_identity",
    "has_usable_api_keys",
    "merge_project_id_into_filters",
    "merge_project_id_into_metadata",
    "require_scope",
    "touch_api_key",
    "verify_api_key",
]
