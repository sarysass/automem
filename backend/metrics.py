"""Aggregated metrics + runtime topology surfaced via /v1/metrics, /v1/healthz,
and /v1/runtime-topology. Pure read-only against tasks.db (no mem0).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.governance_jobs import SUPPORTED_GOVERNANCE_JOB_TYPES
from backend.storage import _resolve_task_db_path, ensure_task_db
from backend.tasks import classify_task_kind


def compute_metrics() -> dict[str, Any]:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        route_rows = conn.execute(
            "SELECT route, COUNT(*) FROM audit_log WHERE event_type = 'memory_route' GROUP BY route"
        ).fetchall()
        event_rows = conn.execute(
            "SELECT event_type, COUNT(*) FROM audit_log GROUP BY event_type"
        ).fetchall()
        task_rows = conn.execute(
            "SELECT task_id, title, last_summary, source_agent, project_id, status FROM tasks"
        ).fetchall()
        memory_domain_rows = conn.execute(
            "SELECT COALESCE(domain, 'unknown') AS domain, COUNT(*) AS count FROM memory_cache GROUP BY COALESCE(domain, 'unknown')"
        ).fetchall()
        memory_category_rows = conn.execute(
            "SELECT COALESCE(category, 'uncategorized') AS category, COUNT(*) AS count FROM memory_cache GROUP BY COALESCE(category, 'uncategorized')"
        ).fetchall()
        cached_memories = conn.execute("SELECT COUNT(*) FROM memory_cache").fetchone()[0]
        governance_status_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM governance_jobs GROUP BY status"
        ).fetchall()
        governance_type_rows = conn.execute(
            "SELECT job_type, COUNT(*) AS count FROM governance_jobs GROUP BY job_type"
        ).fetchall()
        oldest_pending = conn.execute(
            "SELECT created_at FROM governance_jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        last_completed = conn.execute(
            "SELECT finished_at FROM governance_jobs WHERE status = 'completed' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()

    tasks_by_status: dict[str, int] = {}
    tasks_by_kind: dict[str, int] = {}
    active_work_tasks = 0
    active_non_work_tasks = 0
    for row in task_rows:
        status = str(row["status"] or "unknown")
        tasks_by_status[status] = tasks_by_status.get(status, 0) + 1
        task_kind = classify_task_kind(
            task_id=row["task_id"],
            title=row["title"],
            last_summary=row["last_summary"],
            source_agent=row["source_agent"],
            project_id=row["project_id"],
        )
        tasks_by_kind[task_kind] = tasks_by_kind.get(task_kind, 0) + 1
        if status == "active":
            if task_kind == "work":
                active_work_tasks += 1
            else:
                active_non_work_tasks += 1

    return {
        "routes": {row[0] or "unknown": row[1] for row in route_rows},
        "events": {row[0]: row[1] for row in event_rows},
        "tasks": {
            "active": tasks_by_status.get("active", 0),
            "archived": tasks_by_status.get("archived", 0),
            "by_status": tasks_by_status,
            "by_kind": tasks_by_kind,
            "active_work": active_work_tasks,
            "active_non_work": active_non_work_tasks,
        },
        "memory_cache": {
            "entries": cached_memories,
            "by_domain": {row["domain"]: row["count"] for row in memory_domain_rows},
            "by_category": {row["category"]: row["count"] for row in memory_category_rows},
        },
        "governance_jobs": {
            "by_status": {row["status"]: row["count"] for row in governance_status_rows},
            "by_type": {row["job_type"]: row["count"] for row in governance_type_rows},
            "pending": next((row["count"] for row in governance_status_rows if row["status"] == "pending"), 0),
            "running": next((row["count"] for row in governance_status_rows if row["status"] == "running"), 0),
            "failed": next((row["count"] for row in governance_status_rows if row["status"] == "failed"), 0),
            "completed": next((row["count"] for row in governance_status_rows if row["status"] == "completed"), 0),
            "oldest_pending_created_at": str(oldest_pending["created_at"]) if oldest_pending else None,
            "last_completed_at": str(last_completed["finished_at"]) if last_completed else None,
        },
    }


def build_runtime_topology() -> dict[str, Any]:
    return {
        "api": {
            "role": "hot_path_admission_and_query",
            "hot_path_endpoints": [
                "/v1/memory-route",
                "/v1/memories",
                "/v1/task-resolution",
                "/v1/task-summaries",
                "/v1/search",
            ],
            "background_submission_endpoint": "/v1/governance/jobs",
            "notes": [
                "Hot path keeps route, admission, and retrieval synchronous.",
                "Heavy cleanup and maintenance should be queued for the governance worker.",
            ],
        },
        "worker": {
            "role": "background_governance_executor",
            "run_next_endpoint": "/v1/governance/jobs/run-next",
            "supported_job_types": sorted(SUPPORTED_GOVERNANCE_JOB_TYPES),
            "script_entrypoints": [
                "scripts/governance_worker.py",
                "scripts/scheduled_consolidate.py",
            ],
            "contracts": [
                "Jobs are idempotent through caller-supplied idempotency keys.",
                "Workers recover stale running jobs after lease expiry.",
            ],
        },
        "mcp_control_plane": {
            "role": "distribution_and_tooling_surface",
            "allowed_hot_path_tools": [
                "memory_route",
                "memory_capture",
                "memory_search",
                "task_summary_store",
                "memory_metrics",
            ],
            "notes": [
                "Adapters should not embed local governance cleanup branches.",
                "Background governance belongs to API-owned jobs and workers.",
            ],
        },
    }


__all__ = ["build_runtime_topology", "compute_metrics"]
