"""Business orchestration services: store/governance/consolidation/archive.

The 5 functions extracted here orchestrate the multi-step workflows that
glue together mem0 (vector store), the SQLite memory_cache table, the
governance/judge layer, and the audit log:

- store_memory_with_governance — POST /v1/memories ingest path. Runs the
  governance text decision (skip/canonicalize/store), classifies long-term
  facts (duplicate/conflict/supersede), writes to mem0 via memory_backend
  and mirrors into memory_cache, and (on conflict + auto-supersede) calls
  archive_active_long_term_facts to retire older facts.

- dispatch_governance_job — governance worker entry point. Dispatches a
  claimed `governance_jobs` row to run_consolidation_operation, writes
  audit events, and finalizes job state. scripts/governance_worker.py
  imports this DIRECTLY from `backend.main` (legacy path). main.py
  re-exports it from this module to keep that import working.

- rebuild_memory_cache — POST /v1/cache/rebuild + tasks_normalize support.
  Pulls every memory in scope from memory_backend.get_all() and rewrites
  the memory_cache table; deletes stale rows that no longer exist in the
  vector store.

- archive_active_long_term_facts — supersession helper. Replays each
  active fact into mem0 with status=superseded + valid_to + superseded_by,
  then deletes the original. Called from store_memory_with_governance
  (auto-supersede on conflict) and from run_consolidation_operation
  (legacy backfill path).

- run_consolidation_operation — POST /v1/consolidate + governance worker
  consolidate jobs. The big one: rebuilds cache, runs the offline judge
  over every cached memory, dedups + canonicalizes long-term facts,
  archives closed tasks, and (when dedupe_long_term=True) actually
  rewrites canonical text + deletes duplicates/noise in the backend.

Module-isolation contract (read tests/conftest.py):
The test suite re-imports backend/main.py via importlib.spec_from_file_location
under a synthetic module name `automem_backend_<tmp>`. That fixture instance
is NOT the canonical `backend.main`. So MEMORY_BACKEND is seeded ONLY on
the per-test instance. To stay compatible with both the production
single-import path and the test re-import path, every function here takes
`memory_backend` as a keyword-only INJECTED parameter. The FastAPI
handlers in main.py pass `memory_backend=get_memory_backend()` at call
time, which resolves to whichever module the request is actually running
under. Same DI pattern as backend.search_pipeline.hybrid_search and
backend.task_storage.normalize_tasks.

Cross-function calls inside this module pass memory_backend through
directly (e.g., dispatch_governance_job → run_consolidation_operation →
archive_active_long_term_facts).

Symbols still accessed via lazy `from backend import main as _main`:
- _main.normalize_text — small pure utility that still lives in main.py.
  Lazy lookup is safe here since normalize_text is env-transparent (pure
  string normalization, no MEMORY_BACKEND / TASK_DB_PATH dependence).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from backend.audit_log import write_audit
from backend.governance_jobs import (
    GOVERNANCE_JOB_STATUS_COMPLETED,
    GOVERNANCE_JOB_STATUS_FAILED,
    finalize_governance_job,
    release_governance_job_for_retry,
)
from backend.long_term import (
    extract_primary_message_text,
    govern_memory_text,
)
from backend.memory_cache import (
    LONG_TERM_FACT_STATUS_ACTIVE,
    LONG_TERM_FACT_STATUS_CONFLICT_REVIEW,
    LONG_TERM_FACT_STATUS_SUPERSEDED,
    build_long_term_fact_metadata,
    build_metadata_from_cache_row,
    cache_memory_record,
    delete_cached_memory,
    fetch_active_long_term_fact_rows,
    load_long_term_cache_rows,
    long_term_status_from_metadata,
    should_auto_supersede_fact,
)
from backend.schemas import ConsolidateRequest, Message
from backend.storage import _resolve_task_db_path, ensure_task_db, utcnow_iso
from backend.task_storage import normalize_tasks
from governance import build_long_term_duplicate_key, should_run_offline_judge

logger = logging.getLogger("automem.services")


def _normalize_text(text: str) -> str:
    """Lazy lookup of main.normalize_text to honor per-test module isolation."""
    from backend import main as _main

    return _main.normalize_text(text)


def _extract_memory_id(result: Any) -> Optional[str]:
    """Local copy of main.extract_memory_id — pure helper, safe to duplicate."""
    if isinstance(result, dict):
        if result.get("id"):
            return str(result["id"])
        results = result.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict) and first.get("id"):
                return str(first["id"])
    return None


def store_memory_with_governance(
    *,
    messages: list[dict[str, str]],
    user_id: Optional[str],
    run_id: Optional[str],
    agent_id: Optional[str],
    metadata: Optional[dict[str, Any]],
    infer: bool,
    memory_backend: Any,
) -> dict[str, Any]:
    raw_text = extract_primary_message_text([Message(**message) for message in messages])
    governed = govern_memory_text(raw_text, metadata, origin="memory_store")
    if governed["action"] == "skip":
        return {
            "status": "skipped",
            "reason": governed["reason"],
            "noise_kind": governed.get("noise_kind"),
            "judge": "llm" if governed.get("from_llm") else "heuristic",
            "results": [],
        }

    stored_text = str(governed["text"])
    meta = dict(metadata or {})
    if str(meta.get("domain") or "") == "long_term" and not meta.get("category") and governed.get("memory_kind"):
        candidate_category = str(governed["memory_kind"])
        if candidate_category in {"user_profile", "preference", "project_rule", "project_context", "architecture_decision"}:
            meta["category"] = candidate_category
    now = utcnow_iso()
    fact_action = "stored"
    fact_status = None
    fact_key = None
    superseded_rows: list[dict[str, Any]] = []
    superseded_memory_ids: list[str] = []
    conflicts_with: list[str] = []

    if str(meta.get("domain") or "") == "long_term":
        meta = build_long_term_fact_metadata(text=stored_text, metadata=meta, created_at=now)
        fact_key = str(meta.get("fact_key") or "")
        fact_status = str(meta.get("status") or LONG_TERM_FACT_STATUS_ACTIVE)
        auto_supersede = should_auto_supersede_fact(meta)
        active_rows = fetch_active_long_term_fact_rows(
            user_id=user_id,
            project_id=meta.get("project_id"),
            fact_key=fact_key,
            category=str(meta.get("category") or ""),
        )
        duplicate_rows = [
            row
            for row in active_rows
            if _normalize_text(str(row.get("text") or "")) == _normalize_text(stored_text)
        ]
        conflicting_rows = [
            row
            for row in active_rows
            if _normalize_text(str(row.get("text") or "")) != _normalize_text(stored_text)
        ]
        if duplicate_rows and auto_supersede and not conflicting_rows:
            return {
                "status": "skipped",
                "reason": "duplicate",
                "existing_memory_id": str(duplicate_rows[0]["memory_id"]),
                "results": [],
                "fact_status": LONG_TERM_FACT_STATUS_ACTIVE,
                "fact_action": "duplicate",
                "fact_key": fact_key,
            }
        if conflicting_rows:
            if auto_supersede:
                superseded_rows = active_rows
                superseded_memory_ids = [str(row["memory_id"]) for row in active_rows]
                meta = build_long_term_fact_metadata(
                    text=stored_text,
                    metadata=meta,
                    created_at=now,
                    status=LONG_TERM_FACT_STATUS_ACTIVE,
                    supersedes=superseded_memory_ids,
                )
                fact_action = "superseded"
            else:
                conflicts_with = [str(row["memory_id"]) for row in conflicting_rows]
                meta = build_long_term_fact_metadata(
                    text=stored_text,
                    metadata=meta,
                    created_at=now,
                    status=LONG_TERM_FACT_STATUS_CONFLICT_REVIEW,
                    conflicts_with=conflicts_with,
                    conflict_status="needs_review",
                    review_status="pending",
                )
                fact_action = "review_required"
            fact_status = str(meta.get("status") or LONG_TERM_FACT_STATUS_ACTIVE)

    if infer:
        result = memory_backend.add(
            messages=[{"role": "user", "content": stored_text}],
            user_id=user_id,
            run_id=run_id,
            agent_id=agent_id,
            metadata=meta,
            infer=True,
        )
        memory_id = _extract_memory_id(result)
        if memory_id:
            cache_memory_record(
                memory_id=memory_id,
                text=stored_text,
                user_id=user_id,
                run_id=run_id,
                agent_id=agent_id,
                metadata=meta,
                created_at=now,
            )
            if superseded_rows:
                try:
                    archive_active_long_term_facts(
                        superseded_rows,
                        superseded_by=memory_id,
                        archived_at=now,
                        memory_backend=memory_backend,
                    )
                except Exception:
                    memory_backend.delete(memory_id=memory_id)
                    delete_cached_memory(memory_id)
                    raise
        if governed.get("canonicalized"):
            result["status"] = "stored"
            result["canonicalized_from"] = raw_text
        result["judge"] = "llm" if governed.get("from_llm") else "heuristic"
        if fact_status:
            result["fact_status"] = fact_status
            result["fact_action"] = fact_action
            result["fact_key"] = fact_key
        if superseded_memory_ids:
            result["superseded_memory_ids"] = superseded_memory_ids
        if conflicts_with:
            result["conflicts_with"] = conflicts_with
        return result

    result = memory_backend.add(
        messages=[{"role": "user", "content": stored_text}],
        user_id=user_id,
        run_id=run_id,
        agent_id=agent_id,
        metadata=meta,
        infer=False,
    )
    memory_id = _extract_memory_id(result)
    if memory_id:
        cache_memory_record(
            memory_id=memory_id,
            text=stored_text,
            user_id=user_id,
            run_id=run_id,
            agent_id=agent_id,
            metadata=meta,
            created_at=now,
        )
        if superseded_rows:
            try:
                archive_active_long_term_facts(
                    superseded_rows,
                    superseded_by=memory_id,
                    archived_at=now,
                    memory_backend=memory_backend,
                )
            except Exception:
                memory_backend.delete(memory_id=memory_id)
                delete_cached_memory(memory_id)
                raise
    if governed.get("canonicalized"):
        result["status"] = "stored"
        result["canonicalized_from"] = raw_text
    result["judge"] = "llm" if governed.get("from_llm") else "heuristic"
    if fact_status:
        result["fact_status"] = fact_status
        result["fact_action"] = fact_action
        result["fact_key"] = fact_key
    if superseded_memory_ids:
        result["superseded_memory_ids"] = superseded_memory_ids
    if conflicts_with:
        result["conflicts_with"] = conflicts_with
    return result


def dispatch_governance_job(
    job: dict[str, Any],
    *,
    worker_id: str,
    memory_backend: Any,
) -> dict[str, Any]:
    job_id = str(job["job_id"])
    job_type = str(job["job_type"])
    payload = dict(job.get("payload") or {})
    if job_type != "consolidate":
        return finalize_governance_job(
            job_id=job_id,
            status=GOVERNANCE_JOB_STATUS_FAILED,
            result=None,
            error_text=f"Unsupported governance job type: {job_type}",
        )
    try:
        response = run_consolidation_operation(
            ConsolidateRequest(**payload),
            runtime_path="governance_worker",
            worker_id=worker_id,
            job_id=job_id,
            memory_backend=memory_backend,
        )
        write_audit(
            actor_type="governance_worker",
            actor_label=worker_id,
            actor_agent_id=worker_id,
            event_type="consolidate",
            user_id=response.get("user_id"),
            project_id=response.get("project_id"),
            detail=response,
        )
        write_audit(
            actor_type="governance_worker",
            actor_label=worker_id,
            actor_agent_id=worker_id,
            event_type="governance_job_complete",
            user_id=response.get("user_id"),
            project_id=response.get("project_id"),
            detail={
                "job_id": job_id,
                "job_type": job_type,
                "runtime_path": response.get("runtime_path"),
                "result": response,
            },
        )
        return finalize_governance_job(
            job_id=job_id,
            status=GOVERNANCE_JOB_STATUS_COMPLETED,
            result=response,
            error_text=None,
        )
    except Exception as exc:
        released = release_governance_job_for_retry(job_id=job_id, error_text=str(exc))
        write_audit(
            actor_type="governance_worker",
            actor_label=worker_id,
            actor_agent_id=worker_id,
            event_type="governance_job_failed",
            user_id=job.get("user_id"),
            project_id=job.get("project_id"),
            detail={
                "job_id": job_id,
                "job_type": job_type,
                "attempts": released.get("attempts"),
                "max_attempts": released.get("max_attempts"),
                "status": released.get("status"),
                "error": str(exc),
            },
        )
        return released


def rebuild_memory_cache(
    *,
    user_id: Optional[str],
    run_id: Optional[str],
    agent_id: Optional[str],
    memory_backend: Any,
) -> int:
    params = {
        key: value
        for key, value in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items()
        if value is not None
    }
    raw_items = memory_backend.get_all(**params)
    items = raw_items.get("results", []) if isinstance(raw_items, dict) else raw_items
    scope_ids: set[str] = set()
    count = 0
    for item in items or []:
        memory_id = item.get("id")
        text = item.get("memory") or item.get("text")
        if not memory_id or not text:
            continue
        scope_ids.add(str(memory_id))
        cache_memory_record(
            memory_id=str(memory_id),
            text=str(text),
            user_id=item.get("user_id") or user_id,
            run_id=item.get("run_id") or run_id,
            agent_id=item.get("agent_id") or agent_id,
            metadata=item.get("metadata") or {},
            created_at=item.get("created_at"),
        )
        count += 1
    ensure_task_db()
    query = "SELECT memory_id FROM memory_cache WHERE 1=1"
    sql_params: list[Any] = []
    if user_id is not None:
        query += " AND user_id = ?"
        sql_params.append(user_id)
    if run_id is not None:
        query += " AND run_id = ?"
        sql_params.append(run_id)
    if agent_id is not None:
        query += " AND agent_id = ?"
        sql_params.append(agent_id)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        stale_ids = [
            row[0]
            for row in conn.execute(query, sql_params).fetchall()
            if row[0] not in scope_ids
        ]
        if stale_ids:
            conn.executemany("DELETE FROM memory_cache WHERE memory_id = ?", [(memory_id,) for memory_id in stale_ids])
            conn.commit()
    return count


def archive_active_long_term_facts(
    rows: list[dict[str, Any]],
    *,
    superseded_by: str,
    archived_at: str,
    memory_backend: Any,
) -> list[str]:
    archived_history_ids: list[str] = []
    for row in rows:
        memory_id = str(row.get("memory_id") or "")
        if not memory_id:
            continue
        item = memory_backend.get(memory_id)
        if not isinstance(item, dict):
            delete_cached_memory(memory_id)
            continue
        text = str(item.get("memory") or item.get("text") or row.get("text") or "")
        if not text:
            delete_cached_memory(memory_id)
            memory_backend.delete(memory_id=memory_id)
            continue
        base_metadata = {
            **build_metadata_from_cache_row(row),
            **dict(item.get("metadata") or {}),
        }
        archived_metadata = build_long_term_fact_metadata(
            text=text,
            metadata=base_metadata,
            created_at=_normalize_text(str(base_metadata.get("valid_from") or row.get("created_at") or archived_at)) or archived_at,
            status=LONG_TERM_FACT_STATUS_SUPERSEDED,
            superseded_by=superseded_by,
            valid_to=archived_at,
        )
        archived = memory_backend.add(
            messages=[{"role": "user", "content": text}],
            user_id=item.get("user_id") or row.get("user_id"),
            run_id=item.get("run_id") or row.get("run_id"),
            agent_id=item.get("agent_id") or row.get("agent_id"),
            metadata=archived_metadata,
            infer=False,
        )
        archived_id = _extract_memory_id(archived)
        if not archived_id:
            raise RuntimeError(f"Failed to archive superseded fact {memory_id}")
        cache_memory_record(
            memory_id=archived_id,
            text=text,
            user_id=item.get("user_id") or row.get("user_id"),
            run_id=item.get("run_id") or row.get("run_id"),
            agent_id=item.get("agent_id") or row.get("agent_id"),
            metadata=archived_metadata,
            created_at=str(row.get("created_at") or archived_at),
        )
        memory_backend.delete(memory_id=memory_id)
        delete_cached_memory(memory_id)
        archived_history_ids.append(archived_id)
    return archived_history_ids


def run_consolidation_operation(
    payload: ConsolidateRequest,
    *,
    runtime_path: str,
    worker_id: Optional[str] = None,
    job_id: Optional[str] = None,
    memory_backend: Any,
) -> dict[str, Any]:
    ensure_task_db()
    rebuilt_cache_count = 0
    if payload.user_id is not None:
        rebuilt_cache_count = rebuild_memory_cache(
            user_id=payload.user_id,
            run_id=None,
            agent_id=None,
            memory_backend=memory_backend,
        )
    duplicate_memory_ids: list[str] = []
    noise_memory_ids: list[str] = []
    rewrite_rows: list[dict[str, Any]] = []
    canonicalized_long_term_count = 0
    superseded_fact_count = 0
    task_normalize_result = {
        "scanned_tasks": 0,
        "updated_titles": 0,
        "reclassified_non_work": 0,
        "archived_tasks": 0,
        "active_non_work_detected": 0,
        "archived_non_work_detected": 0,
        "deleted_archived_non_work_tasks": 0,
        "deleted_archived_non_work_memory": 0,
        "active_work_without_memory_detected": 0,
        "archived_work_without_memory_detected": 0,
        "archived_work_without_memory_tasks": 0,
        "deleted_archived_work_without_memory_tasks": 0,
        "changed_tasks": 0,
    }
    if payload.normalize_task_state:
        task_normalize_result = normalize_tasks(
            user_id=payload.user_id,
            project_id=payload.project_id,
            archive_non_work_active=True,
            prune_non_work_archived=payload.prune_non_work_archived,
            archive_work_without_memory_active=payload.archive_work_without_memory_active,
            prune_work_without_memory_archived=payload.prune_work_without_memory_archived,
            dry_run=payload.dry_run,
            refresh_cache=False,
            rebuild_cache_fn=lambda **kwargs: rebuild_memory_cache(memory_backend=memory_backend, **kwargs),
            memory_backend=memory_backend if payload.prune_non_work_archived and not payload.dry_run else None,
        )
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        query = """
            SELECT memory_id, user_id, run_id, agent_id, source_agent, domain, category,
                   COALESCE(project_id, '') AS project_id, COALESCE(task_id, '') AS task_id,
                   fact_key, fact_status, valid_from, valid_to, supersedes_json, superseded_by,
                   conflict_status, review_status, text, created_at
            FROM memory_cache
            WHERE 1=1
        """
        params: list[Any] = []
        if payload.user_id is not None:
            query += " AND user_id = ?"
            params.append(payload.user_id)
        if payload.project_id is not None:
            query += " AND project_id = ?"
            params.append(payload.project_id)
        rows = conn.execute(query, params).fetchall()
    long_term_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        metadata = build_metadata_from_cache_row(item)
        origin = "consolidate" if should_run_offline_judge(text=str(item.get("text") or ""), metadata=metadata) else "memory_store"
        governed = govern_memory_text(str(item.get("text") or ""), metadata, origin=origin)
        item["governed"] = governed
        if governed["action"] == "skip":
            noise_memory_ids.append(str(item["memory_id"]))
            continue
        if governed.get("canonicalized"):
            rewrite_rows.append(item | {"canonical_text": str(governed["text"])})
            if item.get("domain") == "long_term":
                canonicalized_long_term_count += 1
        if item.get("domain") != "long_term":
            continue
        item["canonical_text"] = str(governed["text"])
        item["fact_metadata"] = build_long_term_fact_metadata(
            text=item["canonical_text"],
            metadata=metadata,
            created_at=str(item.get("created_at") or utcnow_iso()),
            status=str(metadata.get("status") or LONG_TERM_FACT_STATUS_ACTIVE),
        )
        key = build_long_term_duplicate_key(item)
        long_term_groups.setdefault(key, []).append(item)

    for group in long_term_groups.values():
        ordered = sorted(
            group,
            key=lambda item: (
                1 if str(item.get("text") or "") != str(item.get("canonical_text") or "") else 0,
                str(item.get("created_at") or ""),
                str(item.get("memory_id") or ""),
            ),
        )
        for duplicate in ordered[1:]:
            duplicate_memory_ids.append(str(duplicate["memory_id"]))
    closed_tasks_archived = 0
    if payload.archive_closed_tasks and not payload.dry_run:
        with sqlite3.connect(_resolve_task_db_path()) as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'archived', archived_at = ?, updated_at = ? WHERE status = 'closed'",
                (utcnow_iso(), utcnow_iso()),
            )
            closed_tasks_archived = cursor.rowcount
            conn.commit()
    if payload.dedupe_long_term and not payload.dry_run:
        duplicate_id_set = set(duplicate_memory_ids)
        for memory_id in noise_memory_ids:
            memory_backend.delete(memory_id=memory_id)
            delete_cached_memory(memory_id)
        rewrite_failures: list[str] = []
        for row in rewrite_rows:
            original_memory_id = str(row["memory_id"])
            if original_memory_id in duplicate_id_set:
                continue
            metadata = row.get("fact_metadata") or build_metadata_from_cache_row(row)
            try:
                rewritten = memory_backend.add(
                    messages=[{"role": "user", "content": str(row["canonical_text"])}],
                    user_id=row.get("user_id"),
                    run_id=row.get("run_id"),
                    agent_id=row.get("agent_id"),
                    metadata=metadata,
                    infer=False,
                )
                rewritten_id = _extract_memory_id(rewritten)
                if not rewritten_id:
                    raise RuntimeError("rewrite did not return a memory id")
                cache_memory_record(
                    memory_id=rewritten_id,
                    text=str(row["canonical_text"]),
                    user_id=row.get("user_id"),
                    run_id=row.get("run_id"),
                    agent_id=row.get("agent_id"),
                    metadata=metadata,
                )
                memory_backend.delete(memory_id=original_memory_id)
                delete_cached_memory(original_memory_id)
            except Exception:
                logger.warning("Failed to rewrite canonical memory %s", original_memory_id, exc_info=True)
                rewrite_failures.append(original_memory_id)
        if rewrite_failures:
            raise RuntimeError(f"Failed to rewrite canonical memories: {rewrite_failures[:5]}")
        for memory_id in duplicate_memory_ids:
            memory_backend.delete(memory_id=memory_id)
            delete_cached_memory(memory_id)

    active_fact_rows = load_long_term_cache_rows(user_id=payload.user_id, project_id=payload.project_id)
    fact_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in active_fact_rows:
        fact_metadata = build_long_term_fact_metadata(
            text=str(item.get("text") or ""),
            metadata=build_metadata_from_cache_row(item),
            created_at=str(item.get("created_at") or utcnow_iso()),
            status=str(item.get("fact_status") or LONG_TERM_FACT_STATUS_ACTIVE),
        )
        if long_term_status_from_metadata(fact_metadata) != LONG_TERM_FACT_STATUS_ACTIVE:
            continue
        item["fact_metadata"] = fact_metadata
        fact_groups.setdefault(
            (
                str(item.get("user_id") or ""),
                str(item.get("project_id") or ""),
                str(fact_metadata.get("fact_key") or ""),
            ),
            [],
        ).append(item)

    legacy_supersessions: list[tuple[list[dict[str, Any]], str]] = []
    for group in fact_groups.values():
        if len(group) <= 1:
            continue
        if not should_auto_supersede_fact(group[0].get("fact_metadata")):
            continue
        ordered = sorted(
            group,
            key=lambda item: (
                str((item.get("fact_metadata") or {}).get("valid_from") or item.get("created_at") or ""),
                str(item.get("memory_id") or ""),
            ),
        )
        newest = ordered[-1]
        older = ordered[:-1]
        superseded_fact_count += len(older)
        if older:
            legacy_supersessions.append((older, str(newest.get("memory_id") or "")))

    if not payload.dry_run:
        for older_rows, newest_id in legacy_supersessions:
            archive_active_long_term_facts(
                older_rows,
                superseded_by=newest_id,
                archived_at=utcnow_iso(),
                memory_backend=memory_backend,
            )

    archived_tasks_count = task_normalize_result["archived_tasks"] + closed_tasks_archived
    return {
        "dry_run": payload.dry_run,
        "rebuilt_cache_count": rebuilt_cache_count,
        "duplicate_long_term_count": len(duplicate_memory_ids),
        "canonicalized_long_term_count": canonicalized_long_term_count,
        "superseded_fact_count": superseded_fact_count,
        "deleted_noise_count": len(noise_memory_ids),
        "archived_tasks_count": archived_tasks_count,
        "normalized_tasks_count": task_normalize_result["changed_tasks"],
        "task_reclassified_count": task_normalize_result["archived_tasks"],
        "tasks_scanned_count": task_normalize_result["scanned_tasks"],
        "non_work_tasks_detected_count": task_normalize_result["reclassified_non_work"],
        "active_non_work_detected_count": task_normalize_result["active_non_work_detected"],
        "archived_non_work_detected_count": task_normalize_result["archived_non_work_detected"],
        "deleted_archived_non_work_tasks_count": task_normalize_result["deleted_archived_non_work_tasks"],
        "deleted_archived_non_work_memory_count": task_normalize_result["deleted_archived_non_work_memory"],
        "task_titles_rewritten_count": task_normalize_result["updated_titles"],
        "closed_tasks_archived_count": closed_tasks_archived,
        "user_id": payload.user_id,
        "project_id": payload.project_id,
        "runtime_path": runtime_path,
        "worker_id": worker_id,
        "job_id": job_id,
    }


__all__ = [
    "archive_active_long_term_facts",
    "dispatch_governance_job",
    "rebuild_memory_cache",
    "run_consolidation_operation",
    "store_memory_with_governance",
]
