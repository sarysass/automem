"""Governance jobs storage layer: claim / finalize / enqueue / list.

The dispatch_governance_job orchestration that runs the actual
consolidation work stays in backend.main for now (it depends on
run_consolidation_operation, which is itself ~400 lines and pulls in the
mem0 backend, the task tables, and the governance_judge stack). This
module only owns the SQLite operations on the governance_jobs table.

backend.main re-exports every public name. The governance worker
(scripts/governance_worker.py) imports claim_next_governance_job from
backend.main, so no worker change is needed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

from backend.storage import _resolve_task_db_path, ensure_task_db, utcnow_iso


GOVERNANCE_JOB_STATUS_PENDING = "pending"
GOVERNANCE_JOB_STATUS_RUNNING = "running"
GOVERNANCE_JOB_STATUS_COMPLETED = "completed"
GOVERNANCE_JOB_STATUS_FAILED = "failed"
SUPPORTED_GOVERNANCE_JOB_TYPES = {"consolidate"}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def serialize_governance_job_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    payload_json = item.pop("payload_json", "{}") or "{}"
    result_json = item.pop("result_json", "{}") or "{}"
    item["payload"] = json.loads(payload_json)
    item["result"] = json.loads(result_json)
    item["can_retry"] = bool(
        item.get("status") in {GOVERNANCE_JOB_STATUS_PENDING, GOVERNANCE_JOB_STATUS_RUNNING}
        or (
            item.get("status") == GOVERNANCE_JOB_STATUS_FAILED
            and int(item.get("attempts") or 0) < int(item.get("max_attempts") or 0)
        )
    )
    return item


def fetch_governance_job(job_id: str) -> Optional[dict[str, Any]]:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM governance_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if not row:
        return None
    return serialize_governance_job_row(row)


def list_governance_jobs(
    *,
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_task_db()
    query = "SELECT * FROM governance_jobs WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if job_type:
        query += " AND job_type = ?"
        params.append(job_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [serialize_governance_job_row(row) for row in rows]


def enqueue_governance_job(
    *,
    job_type: str,
    payload: dict[str, Any],
    user_id: Optional[str],
    project_id: Optional[str],
    idempotency_key: Optional[str],
    max_attempts: int,
    created_by: Optional[str],
) -> dict[str, Any]:
    normalized_type = _normalize_text(job_type)
    if normalized_type not in SUPPORTED_GOVERNANCE_JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported governance job type: {job_type}")
    ensure_task_db()
    now = utcnow_iso()
    normalized_key = _normalize_text(idempotency_key or "") or None
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        if normalized_key:
            existing = conn.execute(
                "SELECT * FROM governance_jobs WHERE idempotency_key = ?",
                (normalized_key,),
            ).fetchone()
            if existing:
                job = serialize_governance_job_row(existing)
                job["deduplicated"] = True
                return job
        job_id = f"govjob_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO governance_jobs (
                job_id, job_type, status, idempotency_key, user_id, project_id,
                payload_json, result_json, error_text, attempts, max_attempts,
                lease_expires_at, leased_by, started_at, finished_at, created_by,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '{}', NULL, 0, ?, NULL, NULL, NULL, NULL, ?, ?, ?)
            """,
            (
                job_id,
                normalized_type,
                GOVERNANCE_JOB_STATUS_PENDING,
                normalized_key,
                user_id,
                project_id,
                json.dumps(payload, ensure_ascii=False),
                max(1, min(max_attempts, 10)),
                created_by,
                now,
                now,
            ),
        )
        conn.commit()
    job = fetch_governance_job(job_id)
    assert job is not None
    return job


def claim_next_governance_job(
    *,
    worker_id: str,
    job_types: Optional[list[str]],
    lease_seconds: int,
) -> Optional[dict[str, Any]]:
    ensure_task_db()
    allowed_job_types = sorted(
        {_normalize_text(item) for item in (job_types or []) if _normalize_text(item)}
        & SUPPORTED_GOVERNANCE_JOB_TYPES
    )
    now = utcnow_iso()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=max(30, min(lease_seconds, 3600)))).isoformat()
    query = """
        SELECT *
        FROM governance_jobs
        WHERE (
            status = ?
            OR (status = ? AND COALESCE(lease_expires_at, '') != '' AND lease_expires_at <= ?)
        )
    """
    params: list[Any] = [
        GOVERNANCE_JOB_STATUS_PENDING,
        GOVERNANCE_JOB_STATUS_RUNNING,
        now,
    ]
    if allowed_job_types:
        placeholders = ", ".join("?" for _ in allowed_job_types)
        query += f" AND job_type IN ({placeholders})"
        params.extend(allowed_job_types)
    query += " ORDER BY created_at ASC LIMIT 1"
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(query, params).fetchone()
        if not row:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE governance_jobs
            SET status = ?,
                attempts = attempts + 1,
                lease_expires_at = ?,
                leased_by = ?,
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                GOVERNANCE_JOB_STATUS_RUNNING,
                lease_until,
                worker_id,
                now,
                now,
                row["job_id"],
            ),
        )
        conn.commit()
    claimed = fetch_governance_job(str(row["job_id"]))
    assert claimed is not None
    return claimed


def claim_governance_job_by_id(
    *,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
) -> Optional[dict[str, Any]]:
    ensure_task_db()
    now = utcnow_iso()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=max(30, min(lease_seconds, 3600)))).isoformat()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM governance_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            conn.commit()
            return None
        current_status = str(row["status"] or "")
        lease_expires_at = str(row["lease_expires_at"] or "")
        if current_status not in {GOVERNANCE_JOB_STATUS_PENDING, GOVERNANCE_JOB_STATUS_RUNNING}:
            conn.commit()
            return None
        if current_status == GOVERNANCE_JOB_STATUS_RUNNING and lease_expires_at and lease_expires_at > now:
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE governance_jobs
            SET status = ?,
                attempts = attempts + 1,
                lease_expires_at = ?,
                leased_by = ?,
                started_at = COALESCE(started_at, ?),
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                GOVERNANCE_JOB_STATUS_RUNNING,
                lease_until,
                worker_id,
                now,
                now,
                job_id,
            ),
        )
        conn.commit()
    claimed = fetch_governance_job(job_id)
    assert claimed is not None
    return claimed


def finalize_governance_job(
    *,
    job_id: str,
    status: str,
    result: Optional[dict[str, Any]],
    error_text: Optional[str],
) -> dict[str, Any]:
    ensure_task_db()
    now = utcnow_iso()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.execute(
            """
            UPDATE governance_jobs
            SET status = ?,
                result_json = ?,
                error_text = ?,
                lease_expires_at = NULL,
                leased_by = NULL,
                finished_at = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                status,
                json.dumps(result or {}, ensure_ascii=False),
                error_text,
                now,
                now,
                job_id,
            ),
        )
        conn.commit()
    job = fetch_governance_job(job_id)
    assert job is not None
    return job


def release_governance_job_for_retry(*, job_id: str, error_text: str) -> dict[str, Any]:
    ensure_task_db()
    now = utcnow_iso()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT attempts, max_attempts FROM governance_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Missing governance job {job_id}")
        attempts = int(row["attempts"] or 0)
        max_attempts = int(row["max_attempts"] or 0)
        next_status = (
            GOVERNANCE_JOB_STATUS_PENDING
            if attempts < max_attempts
            else GOVERNANCE_JOB_STATUS_FAILED
        )
        conn.execute(
            """
            UPDATE governance_jobs
            SET status = ?,
                error_text = ?,
                lease_expires_at = NULL,
                leased_by = NULL,
                updated_at = ?
            WHERE job_id = ?
            """,
            (
                next_status,
                error_text,
                now,
                job_id,
            ),
        )
        conn.commit()
    job = fetch_governance_job(job_id)
    assert job is not None
    return job


__all__ = [
    "GOVERNANCE_JOB_STATUS_COMPLETED",
    "GOVERNANCE_JOB_STATUS_FAILED",
    "GOVERNANCE_JOB_STATUS_PENDING",
    "GOVERNANCE_JOB_STATUS_RUNNING",
    "SUPPORTED_GOVERNANCE_JOB_TYPES",
    "claim_governance_job_by_id",
    "claim_next_governance_job",
    "enqueue_governance_job",
    "fetch_governance_job",
    "finalize_governance_job",
    "list_governance_jobs",
    "release_governance_job_for_retry",
    "serialize_governance_job_row",
]
