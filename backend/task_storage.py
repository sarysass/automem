"""Task table storage: row hydration, pagination cursors, page/list/normalize/upsert.

Owns all SQLite + sqlite3.Row -> dict translation for the `tasks` table:

- hydrate_task_row / encode_task_cursor / decode_task_cursor — shape +
  cursor encoding for list endpoints.
- fetch_tasks_page / fetch_tasks — keyset-paged + non-paged listings.
- fetch_task_ids_with_memory — projection from memory_cache used by
  normalize_tasks to detect work tasks lacking memory rows.
- fetch_task_search_context — title/aliases/status lookup for the
  search reranker (backend.search_pipeline).
- normalize_tasks — bulk cleanup pass: title sanitization, non-work
  archive/prune, work-without-memory archive/prune.
- upsert_task — INSERT-or-UPDATE used by route_memory + task_resolution.

Uses _resolve_task_db_path() at call time so each invocation reads the
current TASK_DB_PATH (test fixtures monkeypatch.setenv per-test).

Memory-backend dependency (used by normalize_tasks for cache rebuild +
prune-memory steps) is INJECTED by the caller as
`rebuild_cache_fn` + `memory_backend` parameters. This avoids any
`from backend import main as _main` lookup, which would resolve to the
CANONICAL backend.main module — not the test fixture's freshly-loaded
instance under name `automem_backend_<tmp>`. The canonical instance
has no FakeMemory seeded, so any MEMORY_BACKEND access there triggers
real Memory.from_config(...) and fails on the live ollama/qdrant
endpoints. Dependency injection keeps task_storage.py module-pure.
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from typing import Any, Callable, Optional

from fastapi import HTTPException

from backend.storage import _resolve_task_db_path, ensure_task_db, utcnow_iso
from backend.tasks import (
    classify_task_kind,
    sanitize_task_summary_preview,
    sanitize_task_title,
    task_display_title,
)

logger = logging.getLogger("automem.task_storage")


def fetch_task_search_context(
    *,
    user_id: Optional[str],
    project_id: Optional[str],
    task_ids: Optional[list[str]] = None,
) -> dict[str, dict[str, Any]]:
    ensure_task_db()
    query = "SELECT task_id, title, aliases_json, status, project_id FROM tasks WHERE 1=1"
    params: list[Any] = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if project_id is not None:
        query += " AND project_id IS ?"
        params.append(project_id)
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        query += f" AND task_id IN ({placeholders})"
        params.extend(task_ids)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    context: dict[str, dict[str, Any]] = {}
    for row in rows:
        context[str(row["task_id"])] = {
            "title": str(row["title"] or ""),
            "aliases": json.loads(row["aliases_json"] or "[]"),
            "status": str(row["status"] or "active"),
            "project_id": row["project_id"],
        }
    return context


def hydrate_task_row(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    task["aliases"] = json.loads(task.pop("aliases_json") or "[]")
    task["title"] = task_display_title(task)
    task["task_kind"] = classify_task_kind(
        task_id=task.get("task_id"),
        title=task.get("title"),
        last_summary=task.get("last_summary"),
        source_agent=task.get("source_agent"),
        project_id=task.get("project_id"),
    )
    task["display_title"] = task["title"]
    task["summary_preview"] = sanitize_task_summary_preview(task.get("last_summary"))
    return task


def encode_task_cursor(updated_at: Optional[str], task_id: str) -> str:
    payload = json.dumps({"updated_at": updated_at or "", "task_id": task_id}, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_task_cursor(cursor: str) -> tuple[str, str]:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid tasks cursor") from exc
    updated_at = str(payload.get("updated_at") or "")
    task_id = str(payload.get("task_id") or "")
    if not task_id:
        raise HTTPException(status_code=400, detail="Invalid tasks cursor")
    return updated_at, task_id


def fetch_tasks_page(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 50,
    cursor: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str], bool]:
    ensure_task_db()
    query = "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE 1=1"
    params: list[Any] = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if project_id is not None:
        query += " AND project_id IS ?"
        params.append(project_id)
    if status:
        query += " AND status = ?"
        params.append(status)
    page_size = max(1, min(limit, 200))
    if cursor:
        cursor_updated_at, cursor_task_id = decode_task_cursor(cursor)
        query += " AND ((updated_at < ?) OR (updated_at = ? AND task_id < ?))"
        params.extend([cursor_updated_at, cursor_updated_at, cursor_task_id])
    query += " ORDER BY updated_at DESC, task_id DESC LIMIT ?"
    params.append(page_size + 1)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    tasks = [hydrate_task_row(row) for row in page_rows]
    next_cursor = None
    if has_more and tasks:
        last = tasks[-1]
        next_cursor = encode_task_cursor(last.get("updated_at"), str(last["task_id"]))
    return tasks, next_cursor, has_more


def fetch_tasks(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 50,
) -> list[dict[str, Any]]:
    tasks, _next_cursor, _has_more = fetch_tasks_page(
        user_id=user_id,
        project_id=project_id,
        status=status,
        limit=limit,
    )
    return tasks


def fetch_task_ids_with_memory(
    *,
    user_id: Optional[str],
    project_id: Optional[str],
) -> set[str]:
    ensure_task_db()
    query = """
        SELECT DISTINCT COALESCE(NULLIF(task_id, ''), NULLIF(run_id, '')) AS effective_task_id
        FROM memory_cache
        WHERE domain = 'task'
          AND COALESCE(NULLIF(task_id, ''), NULLIF(run_id, '')) IS NOT NULL
    """
    params: list[Any] = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if project_id is not None:
        query += " AND project_id IS ?"
        params.append(project_id)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        rows = conn.execute(query, params).fetchall()
    return {str(row[0]) for row in rows if row and row[0]}


def normalize_tasks(
    *,
    user_id: Optional[str],
    project_id: Optional[str],
    archive_non_work_active: bool,
    prune_non_work_archived: bool,
    archive_work_without_memory_active: bool,
    prune_work_without_memory_archived: bool,
    dry_run: bool,
    refresh_cache: bool = True,
    rebuild_cache_fn: Optional[Callable[..., int]] = None,
    memory_backend: Any = None,
) -> dict[str, int]:
    # Memory-backend deps injected by caller. See module docstring for why
    # we don't reach into backend.main via lazy import.
    rebuilt_cache_count = 0
    if refresh_cache and rebuild_cache_fn is not None:
        rebuilt_cache_count = rebuild_cache_fn(user_id=user_id, run_id=None, agent_id=None)
    ensure_task_db()
    query = """
        SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent,
               owner_agent, priority, created_at, updated_at, closed_at, archived_at
        FROM tasks
        WHERE 1=1
    """
    params: list[Any] = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if project_id is not None:
        query += " AND project_id IS ?"
        params.append(project_id)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()

    updated_titles = 0
    archived_tasks = 0
    kinds_reclassified = 0
    active_non_work_detected = 0
    archived_non_work_detected = 0
    deleted_archived_non_work_tasks = 0
    deleted_archived_non_work_memory = 0
    active_work_without_memory_detected = 0
    archived_work_without_memory_detected = 0
    archived_work_without_memory_tasks = 0
    deleted_archived_work_without_memory_tasks = 0
    changed_task_ids: set[str] = set()
    archived_non_work_task_ids_to_delete: list[str] = []
    archived_work_without_memory_task_ids_to_delete: list[str] = []
    task_ids_with_memory = fetch_task_ids_with_memory(user_id=user_id, project_id=project_id)
    now = utcnow_iso()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        for row in rows:
            task = dict(row)
            old_title = task.get("title") or ""
            normalized_title = sanitize_task_title(
                task.get("title"),
                last_summary=task.get("last_summary"),
                task_id=task.get("task_id"),
            )
            task_kind = classify_task_kind(
                task_id=task.get("task_id"),
                title=normalized_title,
                last_summary=task.get("last_summary"),
                source_agent=task.get("source_agent"),
                project_id=task.get("project_id"),
            )
            if normalized_title != old_title:
                updated_titles += 1
                changed_task_ids.add(task["task_id"])
                if not dry_run:
                    conn.execute(
                        "UPDATE tasks SET title = ?, updated_at = ? WHERE task_id = ?",
                        (normalized_title, now, task["task_id"]),
                    )
            if task_kind != "work":
                kinds_reclassified += 1
                if task.get("status") == "active":
                    active_non_work_detected += 1
                elif task.get("status") == "archived":
                    archived_non_work_detected += 1
                    if prune_non_work_archived:
                        archived_non_work_task_ids_to_delete.append(str(task["task_id"]))
                if archive_non_work_active and task.get("status") == "active":
                    archived_tasks += 1
                    changed_task_ids.add(task["task_id"])
                    if not dry_run:
                        conn.execute(
                            "UPDATE tasks SET status = 'archived', archived_at = COALESCE(archived_at, ?), updated_at = ? WHERE task_id = ?",
                            (now, now, task["task_id"]),
                        )
                continue

            if str(task["task_id"]) not in task_ids_with_memory:
                if task.get("status") == "active":
                    active_work_without_memory_detected += 1
                    if archive_work_without_memory_active:
                        archived_work_without_memory_tasks += 1
                        changed_task_ids.add(task["task_id"])
                        if not dry_run:
                            conn.execute(
                                "UPDATE tasks SET status = 'archived', archived_at = COALESCE(archived_at, ?), updated_at = ? WHERE task_id = ?",
                                (now, now, task["task_id"]),
                            )
                elif task.get("status") == "archived":
                    archived_work_without_memory_detected += 1
                    if prune_work_without_memory_archived:
                        archived_work_without_memory_task_ids_to_delete.append(str(task["task_id"]))
        if prune_non_work_archived and archived_non_work_task_ids_to_delete:
            deleted_archived_non_work_tasks = len(archived_non_work_task_ids_to_delete)
            if not dry_run:
                placeholders = ",".join("?" for _ in archived_non_work_task_ids_to_delete)
                memory_rows = conn.execute(
                    f"""
                    SELECT memory_id
                    FROM memory_cache
                    WHERE domain = 'task'
                      AND (task_id IN ({placeholders}) OR run_id IN ({placeholders}))
                    """,
                    [*archived_non_work_task_ids_to_delete, *archived_non_work_task_ids_to_delete],
                ).fetchall()
                memory_ids = [str(row[0]) for row in memory_rows]
                deleted_memory_ids: list[str] = []
                failed_memory_ids: list[str] = []
                for memory_id in memory_ids:
                    try:
                        if memory_backend is None:
                            raise RuntimeError("normalize_tasks: prune path requires memory_backend")
                        memory_backend.delete(memory_id=memory_id)
                        deleted_memory_ids.append(memory_id)
                    except Exception:
                        logger.warning("Failed to delete archived non-work task memory %s", memory_id, exc_info=True)
                        failed_memory_ids.append(memory_id)
                deleted_archived_non_work_memory = len(deleted_memory_ids)
                if deleted_memory_ids:
                    conn.executemany("DELETE FROM memory_cache WHERE memory_id = ?", [(memory_id,) for memory_id in deleted_memory_ids])
                if failed_memory_ids:
                    deleted_archived_non_work_tasks = 0
                    raise RuntimeError(
                        f"Failed to delete archived non-work task memories: {failed_memory_ids[:5]}"
                    )
                conn.execute(
                    f"DELETE FROM tasks WHERE task_id IN ({placeholders})",
                    archived_non_work_task_ids_to_delete,
                )
        if prune_work_without_memory_archived and archived_work_without_memory_task_ids_to_delete:
            deleted_archived_work_without_memory_tasks = len(archived_work_without_memory_task_ids_to_delete)
            if not dry_run:
                placeholders = ",".join("?" for _ in archived_work_without_memory_task_ids_to_delete)
                conn.execute(
                    f"DELETE FROM tasks WHERE task_id IN ({placeholders})",
                    archived_work_without_memory_task_ids_to_delete,
                )
        if not dry_run:
            conn.commit()

    return {
        "scanned_tasks": len(rows),
        "rebuilt_cache_count": rebuilt_cache_count,
        "updated_titles": updated_titles,
        "reclassified_non_work": kinds_reclassified,
        "active_non_work_detected": active_non_work_detected,
        "archived_non_work_detected": archived_non_work_detected,
        "archived_tasks": archived_tasks,
        "deleted_archived_non_work_tasks": deleted_archived_non_work_tasks,
        "deleted_archived_non_work_memory": deleted_archived_non_work_memory,
        "active_work_without_memory_detected": active_work_without_memory_detected,
        "archived_work_without_memory_detected": archived_work_without_memory_detected,
        "archived_work_without_memory_tasks": archived_work_without_memory_tasks,
        "deleted_archived_work_without_memory_tasks": deleted_archived_work_without_memory_tasks,
        "changed_tasks": len(changed_task_ids),
    }


def upsert_task(
    *,
    task_id: str,
    user_id: str,
    project_id: Optional[str],
    title: str,
    source_agent: Optional[str],
    last_summary: Optional[str],
    aliases: Optional[list[str]] = None,
) -> dict[str, Any]:
    ensure_task_db()
    now = utcnow_iso()
    title = sanitize_task_title(title, last_summary=last_summary, task_id=task_id)
    aliases_json = json.dumps(aliases or [], ensure_ascii=False)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        existing = conn.execute(
            "SELECT task_id, created_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE tasks
                SET title = ?, project_id = ?, aliases_json = ?, last_summary = ?, source_agent = ?, owner_agent = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (title, project_id, aliases_json, last_summary, source_agent, source_agent, now, task_id),
            )
            created_at = existing[1]
        else:
            conn.execute(
                """
                INSERT INTO tasks (task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, 0, ?, ?)
                """,
                (task_id, user_id, project_id, title, aliases_json, last_summary, source_agent, source_agent, now, now),
            )
            created_at = now
        conn.commit()
    return {
        "task_id": task_id,
        "user_id": user_id,
        "project_id": project_id,
        "title": title,
        "aliases": aliases or [],
        "status": "active",
        "last_summary": last_summary,
        "source_agent": source_agent,
        "owner_agent": source_agent,
        "priority": 0,
        "created_at": created_at,
        "updated_at": now,
        "closed_at": None,
        "archived_at": None,
    }


__all__ = [
    "decode_task_cursor",
    "encode_task_cursor",
    "fetch_task_ids_with_memory",
    "fetch_task_search_context",
    "fetch_tasks",
    "fetch_tasks_page",
    "hydrate_task_row",
    "normalize_tasks",
    "upsert_task",
]
