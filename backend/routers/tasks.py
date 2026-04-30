"""Task lifecycle HTTP handlers (resolution, summaries, list/get, close,
archive, normalize).

See backend/routers/health.py docstring for the app.state.main_module
pattern that lets handlers call get_memory_backend() /
ensure_task_row_access() on the active main module instance under the
per-test importlib reload pattern in tests/conftest.py.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.audit_log import write_audit
from backend.auth import (
    enforce_agent_identity,
    enforce_payload_project_identity,
    enforce_project_identity,
    enforce_user_identity,
    require_scope,
    verify_api_key,
)
from backend.long_term import govern_text_decision
from backend.routing import resolve_task
from backend.schemas import (
    TaskLifecycleRequest,
    TaskNormalizeRequest,
    TaskResolutionRequest,
    TaskSummaryWriteRequest,
)
from backend.services import rebuild_memory_cache, store_memory_with_governance
from backend.storage import _resolve_task_db_path, ensure_task_db, utcnow_iso
from backend.task_storage import fetch_tasks_page, normalize_tasks, upsert_task
from backend.tasks import (
    derive_task_summary,
    evaluate_task_materialization,
    sanitize_task_summary_preview,
    task_display_title,
)
from governance import filter_task_memory_fields, should_store_task_memory

router = APIRouter()


def _main(request: Request):
    return request.app.state.main_module


@router.post("/v1/task-resolution")
def task_resolution(payload: TaskResolutionRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    enforce_payload_project_identity(auth, payload)
    payload.agent_id = enforce_agent_identity(auth, payload.agent_id)
    result = resolve_task(payload)
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=payload.agent_id,
        event_type="task_resolution",
        user_id=payload.user_id,
        project_id=payload.project_id,
        task_id=result.get("task_id"),
        detail={"message": payload.message, "action": result.get("action")},
    )
    return result


@router.post("/v1/task-summaries")
def task_summaries(request: Request, payload: TaskSummaryWriteRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    enforce_payload_project_identity(auth, payload)
    payload.agent_id = enforce_agent_identity(auth, payload.agent_id)
    resolution = None
    task_id = payload.task_id
    title = payload.title
    if not task_id:
        resolution = resolve_task(
            TaskResolutionRequest(
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                project_id=payload.project_id,
                message=payload.message or payload.summary or "",
                assistant_output=payload.assistant_output,
                session_id=payload.session_id,
                channel=payload.channel,
            )
        )
        if resolution["action"] == "no_task":
            return {"action": "skipped", "reason": resolution["reason"]}
        task_id = resolution["task_id"]
        title = title or resolution["title"]

    structured = derive_task_summary(payload)
    should_materialize, task_kind, task_reason = evaluate_task_materialization(
        task_id=task_id,
        title=title or task_id,
        payload=payload,
        structured=structured,
    )
    if not should_materialize:
        return {
            "action": "skipped",
            "reason": task_reason,
            "resolution": resolution,
            "task_kind": task_kind,
            "store_task_memory": False,
        }

    category_map = {
        "summary": "handoff",
        "progress": "progress",
        "blocker": "blocker",
        "next_action": "next_action",
    }
    approved_fields, governance_decisions = filter_task_memory_fields(
        task_kind=task_kind,
        fields=structured,
        judge_field=lambda field, value: govern_text_decision(
            value,
            {
                "domain": "task",
                "source_agent": payload.agent_id,
                "project_id": payload.project_id,
                "category": category_map[field],
                "task_id": task_id,
            },
            origin="task_summary",
        ),
    )

    if not approved_fields:
        return {
            "action": "skipped",
            "reason": "no_task_memory_fields_accepted",
            "resolution": resolution,
            "task_kind": task_kind,
            "governance": governance_decisions,
            "store_task_memory": False,
        }

    task = upsert_task(
        task_id=task_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        title=title or task_id,
        source_agent=payload.agent_id,
        last_summary=structured["summary"] or payload.summary,
        aliases=[],
    )
    task["task_kind"] = task_kind

    memory_backend = _main(request).get_memory_backend()
    stored = []
    for field, value in approved_fields.items():
        result = store_memory_with_governance(
            messages=[{"role": "user", "content": value}],
            user_id=payload.user_id,
            run_id=task_id,
            agent_id=payload.agent_id,
            metadata={
                "domain": "task",
                "source_agent": payload.agent_id,
                "project_id": payload.project_id,
                "category": category_map[field],
                "task_id": task_id,
            },
            infer=False,
            memory_backend=memory_backend,
        )
        stored.append(result)

    return {
        "action": "stored",
        "task": task,
        "resolution": resolution,
        "stored": stored,
        "governance": governance_decisions,
        "store_task_memory": should_store_task_memory(task_kind),
    }


@router.get("/v1/tasks")
def list_tasks(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    status: Optional[str] = "active",
    limit: int = 50,
    cursor: Optional[str] = None,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "task")
    user_id = enforce_user_identity(auth, user_id)
    project_id = enforce_project_identity(auth, project_id)
    if user_id is None and not auth.get("is_admin"):
        raise HTTPException(status_code=400, detail="user_id is required for non-admin keys")
    tasks, next_cursor, has_more = fetch_tasks_page(
        user_id=user_id,
        project_id=project_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    return {
        "tasks": tasks,
        "page_info": {
            "limit": max(1, min(limit, 200)),
            "has_more": has_more,
            "next_cursor": next_cursor,
        },
    }


@router.get("/v1/tasks/{task_id}")
def get_task(request: Request, task_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    task = _main(request).ensure_task_row_access(auth, row)
    task["aliases"] = json.loads(task.pop("aliases_json") or "[]")
    task["title"] = task_display_title(task)
    task["display_title"] = task["title"]
    task["summary_preview"] = sanitize_task_summary_preview(task.get("last_summary"))
    return task


@router.post("/v1/tasks/{task_id}/close")
def close_task(request: Request, task_id: str, payload: TaskLifecycleRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    main = _main(request)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        main.ensure_task_row_access(auth, row)
        now = utcnow_iso()
        cursor = conn.execute(
            "UPDATE tasks SET status = 'closed', closed_at = ?, updated_at = ? WHERE task_id = ? AND status != 'archived'",
            (now, now, task_id),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="task_close",
        task_id=task_id,
        detail={"reason": payload.reason},
    )
    return {"ok": True, "task_id": task_id, "status": "closed"}


@router.post("/v1/tasks/{task_id}/archive")
def archive_task(request: Request, task_id: str, payload: TaskLifecycleRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    main = _main(request)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        main.ensure_task_row_access(auth, row)
        now = utcnow_iso()
        cursor = conn.execute(
            "UPDATE tasks SET status = 'archived', archived_at = ?, updated_at = ? WHERE task_id = ?",
            (now, now, task_id),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="task_archive",
        task_id=task_id,
        detail={"reason": payload.reason},
    )
    return {"ok": True, "task_id": task_id, "status": "archived"}


@router.post("/v1/tasks/normalize")
def tasks_normalize(request: Request, payload: TaskNormalizeRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    backend_for_normalize = _main(request).get_memory_backend()
    result = normalize_tasks(
        user_id=payload.user_id,
        project_id=payload.project_id,
        archive_non_work_active=payload.archive_non_work_active,
        prune_non_work_archived=payload.prune_non_work_archived,
        archive_work_without_memory_active=payload.archive_work_without_memory_active,
        prune_work_without_memory_archived=payload.prune_work_without_memory_archived,
        dry_run=payload.dry_run,
        refresh_cache=True,
        rebuild_cache_fn=lambda **kwargs: rebuild_memory_cache(memory_backend=backend_for_normalize, **kwargs),
        memory_backend=backend_for_normalize if payload.prune_non_work_archived and not payload.dry_run else None,
    )
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="task_normalize",
        user_id=payload.user_id,
        project_id=payload.project_id,
        detail={
            **result,
            "dry_run": payload.dry_run,
            "archive_non_work_active": payload.archive_non_work_active,
            "prune_non_work_archived": payload.prune_non_work_archived,
            "archive_work_without_memory_active": payload.archive_work_without_memory_active,
            "prune_work_without_memory_archived": payload.prune_work_without_memory_archived,
        },
    )
    return {
        **result,
        "dry_run": payload.dry_run,
        "user_id": payload.user_id,
        "project_id": payload.project_id,
        "prune_non_work_archived": payload.prune_non_work_archived,
    }
