"""Audit log storage layer: persist + fetch event records.

The audit_log table is the system's tamper-resistant record of who did
what (admin, agent_key, governance_worker, scheduled task) and when.
Storage is dead simple — INSERT one row per event, query newest-first
with optional event_type filter.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Optional

from backend.storage import _resolve_task_db_path, ensure_task_db, utcnow_iso


def fetch_audit_log(*, limit: int = 50, event_type: Optional[str] = None) -> list[dict[str, Any]]:
    ensure_task_db()
    query = """
        SELECT event_id, created_at, actor_type, actor_label, actor_agent_id, event_type,
               user_id, project_id, task_id, route, detail_json
        FROM audit_log
    """
    params: list[Any] = []
    if event_type:
        query += " WHERE event_type = ?"
        params.append(event_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    entries: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["detail"] = json.loads(item.pop("detail_json") or "{}")
        entries.append(item)
    return entries


def write_audit(
    *,
    actor_type: str,
    actor_label: Optional[str],
    actor_agent_id: Optional[str],
    event_type: str,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    route: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO audit_log (event_id, created_at, actor_type, actor_label, actor_agent_id, event_type, user_id, project_id, task_id, route, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"audit_{uuid.uuid4().hex}",
                utcnow_iso(),
                actor_type,
                actor_label,
                actor_agent_id,
                event_type,
                user_id,
                project_id,
                task_id,
                route,
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
        conn.commit()


__all__ = ["fetch_audit_log", "write_audit"]
