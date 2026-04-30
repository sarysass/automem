"""memory_cache table operations + long-term fact metadata helpers.

memory_cache mirrors mem0's authoritative store with our own
domain-specific columns (fact_key, fact_status, valid_from/valid_to,
supersedes, conflict_status, review_status). It exists to support fast
local FTS5 search and long-term fact lifecycle management without
hitting the vector store.

What stays in backend.main:
- rebuild_memory_cache: pulls items from get_memory_backend() and
  reseeds the cache. Mem0-coupled, doesn't belong in a pure cache layer.
- archive_active_long_term_facts: orchestrates mem0 backend + cache
  during fact supersede flow. Mem0-coupled.
- store_memory_with_governance and the search-side helpers stay too.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any, Optional

from backend.governance.project_lifecycle import PROJECT_CURRENT_FACT_KEYS, infer_project_context_fact_key
from backend.storage import _resolve_task_db_path, ensure_task_db


LONG_TERM_FACT_STATUS_ACTIVE = "active"
LONG_TERM_FACT_STATUS_SUPERSEDED = "superseded"
LONG_TERM_FACT_STATUS_CONFLICT_REVIEW = "conflict_review"
LONG_TERM_FACT_STATUSES = {
    LONG_TERM_FACT_STATUS_ACTIVE,
    LONG_TERM_FACT_STATUS_SUPERSEDED,
    LONG_TERM_FACT_STATUS_CONFLICT_REVIEW,
}
AUTO_SUPERSEDE_FACT_KEYS = {
    "user_profile:name",
    "user_profile:role",
    "preference:language",
    "preference:summary_style",
    *PROJECT_CURRENT_FACT_KEYS,
}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = [stripped]
        else:
            parsed = [stripped]
    elif isinstance(raw, (list, tuple, set)):
        parsed = list(raw)
    else:
        parsed = [raw]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        value = _normalize_text(str(item or ""))
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def normalize_fact_status(raw: Any, *, default: str = LONG_TERM_FACT_STATUS_ACTIVE) -> str:
    value = _normalize_text(str(raw or "")).lower().replace("-", "_").replace(" ", "_")
    if value in LONG_TERM_FACT_STATUSES:
        return value
    return default


def infer_long_term_fact_key(text: str, metadata: Optional[dict[str, Any]]) -> str:
    meta = metadata or {}
    explicit = _normalize_text(str(meta.get("fact_key") or ""))
    if explicit:
        return explicit
    normalized = _normalize_text(text)
    lower = normalized.lower()
    category = str(meta.get("category") or "")
    if category == "preference":
        if re.search(r"中文|英文|语言|沟通|language|communicat|chinese|english", lower, re.I):
            return "preference:language"
        if re.search(r"总结|风格|简洁|直接|summary|style|concise|direct", lower, re.I):
            return "preference:summary_style"
    if category == "user_profile":
        if re.search(r"姓名|名字|我叫|name|called", lower, re.I):
            return "user_profile:name"
        if re.search(r"身份|角色|role|title|ceo|cto|founder|创始人|负责人", lower, re.I):
            return "user_profile:role"
    if category == "project_context":
        project_fact_key = infer_project_context_fact_key(normalized, meta)
        if project_fact_key:
            return project_fact_key
        if re.search(r"公司|company|corp|inc|llc|集团|团队", lower, re.I):
            return "project_context:company"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{category or 'long_term'}:{digest}"


def should_auto_supersede_fact(metadata: Optional[dict[str, Any]]) -> bool:
    meta = metadata or {}
    fact_key = _normalize_text(str(meta.get("fact_key") or ""))
    return fact_key in AUTO_SUPERSEDE_FACT_KEYS


def build_long_term_fact_metadata(
    *,
    text: str,
    metadata: Optional[dict[str, Any]],
    created_at: str,
    status: Optional[str] = None,
    supersedes: Optional[list[str]] = None,
    superseded_by: Optional[str] = None,
    valid_to: Optional[str] = None,
    conflict_status: Optional[str] = None,
    review_status: Optional[str] = None,
    conflicts_with: Optional[list[str]] = None,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    merged["fact_key"] = infer_long_term_fact_key(text, merged)
    merged["status"] = normalize_fact_status(status or merged.get("status"))
    merged["valid_from"] = _normalize_text(str(merged.get("valid_from") or "")) or created_at
    merged["supersedes"] = normalize_string_list(supersedes if supersedes is not None else merged.get("supersedes"))

    if merged["status"] == LONG_TERM_FACT_STATUS_ACTIVE:
        merged.pop("valid_to", None)
        merged.pop("superseded_by", None)
        merged.pop("conflict_status", None)
        merged.pop("review_status", None)
        merged.pop("conflicts_with", None)
        return merged

    if merged["status"] == LONG_TERM_FACT_STATUS_SUPERSEDED:
        merged["valid_to"] = _normalize_text(str(valid_to or merged.get("valid_to") or "")) or created_at
        if superseded_by:
            merged["superseded_by"] = superseded_by
        merged.pop("conflict_status", None)
        merged.pop("review_status", None)
        merged.pop("conflicts_with", None)
        return merged

    merged["conflict_status"] = _normalize_text(str(conflict_status or merged.get("conflict_status") or "needs_review")) or "needs_review"
    merged["review_status"] = _normalize_text(str(review_status or merged.get("review_status") or "pending")) or "pending"
    merged["conflicts_with"] = normalize_string_list(conflicts_with if conflicts_with is not None else merged.get("conflicts_with"))
    merged.pop("superseded_by", None)
    return merged


def long_term_status_from_metadata(metadata: Optional[dict[str, Any]]) -> str:
    return normalize_fact_status((metadata or {}).get("status"))


def find_cached_duplicate_memory_id(
    *,
    text: str,
    user_id: Optional[str],
    run_id: Optional[str],
    agent_id: Optional[str],
    metadata: Optional[dict[str, Any]],
) -> Optional[str]:
    ensure_task_db()
    meta = metadata or {}
    params: list[Any] = [
        _normalize_text(text),
        user_id or "",
        run_id or "",
        agent_id or "",
        str(meta.get("domain") or ""),
        str(meta.get("category") or ""),
        str(meta.get("project_id") or ""),
        str(meta.get("task_id") or ""),
    ]
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        row = conn.execute(
            """
            SELECT memory_id
            FROM memory_cache
            WHERE text = ?
              AND COALESCE(user_id, '') = ?
              AND COALESCE(run_id, '') = ?
              AND COALESCE(agent_id, '') = ?
              AND COALESCE(domain, '') = ?
              AND COALESCE(category, '') = ?
              AND COALESCE(project_id, '') = ?
              AND COALESCE(task_id, '') = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            params,
        ).fetchone()
    return str(row[0]) if row else None


def cache_memory_record(
    *,
    memory_id: str,
    text: str,
    user_id: Optional[str],
    run_id: Optional[str],
    agent_id: Optional[str],
    metadata: Optional[dict[str, Any]],
    created_at: Optional[str] = None,
) -> None:
    from backend.storage import utcnow_iso  # local import: avoid widening top-level deps

    ensure_task_db()
    now = created_at or utcnow_iso()
    meta = dict(metadata or {})
    if str(meta.get("domain") or "") == "long_term":
        meta = build_long_term_fact_metadata(
            text=text,
            metadata=meta,
            created_at=_normalize_text(str(meta.get("valid_from") or "")) or now,
            status=str(meta.get("status") or LONG_TERM_FACT_STATUS_ACTIVE),
        )
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO memory_cache (
                memory_id, user_id, run_id, agent_id, source_agent, domain, category,
                project_id, task_id, fact_key, fact_status, valid_from, valid_to,
                supersedes_json, superseded_by, conflict_status, review_status,
                text, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                user_id = excluded.user_id,
                run_id = excluded.run_id,
                agent_id = excluded.agent_id,
                source_agent = excluded.source_agent,
                domain = excluded.domain,
                category = excluded.category,
                project_id = excluded.project_id,
                task_id = excluded.task_id,
                fact_key = excluded.fact_key,
                fact_status = excluded.fact_status,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                supersedes_json = excluded.supersedes_json,
                superseded_by = excluded.superseded_by,
                conflict_status = excluded.conflict_status,
                review_status = excluded.review_status,
                text = excluded.text,
                updated_at = excluded.updated_at
            """,
            (
                memory_id,
                user_id,
                run_id,
                agent_id,
                meta.get("source_agent"),
                meta.get("domain"),
                meta.get("category"),
                meta.get("project_id"),
                meta.get("task_id"),
                meta.get("fact_key"),
                normalize_fact_status(meta.get("status")),
                meta.get("valid_from"),
                meta.get("valid_to"),
                json.dumps(normalize_string_list(meta.get("supersedes")), ensure_ascii=False),
                meta.get("superseded_by"),
                meta.get("conflict_status"),
                meta.get("review_status"),
                text,
                now,
                now,
            ),
        )
        conn.commit()


def delete_cached_memory(memory_id: str) -> None:
    ensure_task_db()
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.execute("DELETE FROM memory_cache WHERE memory_id = ?", (memory_id,))
        conn.commit()


def build_metadata_from_cache_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "domain": row.get("domain"),
        "category": row.get("category"),
        "project_id": row.get("project_id") or None,
        "task_id": row.get("task_id") or None,
        "source_agent": row.get("source_agent") or None,
    }
    if row.get("fact_key"):
        metadata["fact_key"] = row.get("fact_key")
    if row.get("fact_status"):
        metadata["status"] = normalize_fact_status(row.get("fact_status"))
    if row.get("valid_from"):
        metadata["valid_from"] = row.get("valid_from")
    if row.get("valid_to"):
        metadata["valid_to"] = row.get("valid_to")
    supersedes = normalize_string_list(row.get("supersedes_json"))
    if supersedes:
        metadata["supersedes"] = supersedes
    if row.get("superseded_by"):
        metadata["superseded_by"] = row.get("superseded_by")
    if row.get("conflict_status"):
        metadata["conflict_status"] = row.get("conflict_status")
    if row.get("review_status"):
        metadata["review_status"] = row.get("review_status")
    return metadata


def load_long_term_cache_rows(*, user_id: Optional[str], project_id: Optional[str]) -> list[dict[str, Any]]:
    ensure_task_db()
    query = """
        SELECT memory_id, user_id, run_id, agent_id, source_agent, domain, category,
               project_id, task_id, fact_key, fact_status, valid_from, valid_to,
               supersedes_json, superseded_by, conflict_status, review_status,
               text, created_at, updated_at
        FROM memory_cache
        WHERE domain = 'long_term'
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
    return [dict(row) for row in rows]


def fetch_active_long_term_fact_rows(
    *,
    user_id: Optional[str],
    project_id: Optional[str],
    fact_key: str,
    category: Optional[str],
) -> list[dict[str, Any]]:
    ensure_task_db()
    query = """
        SELECT memory_id, user_id, run_id, agent_id, source_agent, domain, category,
               project_id, task_id, fact_key, fact_status, valid_from, valid_to,
               supersedes_json, superseded_by, conflict_status, review_status,
               text, created_at, updated_at
        FROM memory_cache
        WHERE domain = 'long_term'
          AND fact_key = ?
          AND fact_status = ?
    """
    params: list[Any] = [fact_key, LONG_TERM_FACT_STATUS_ACTIVE]
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if project_id is not None:
        query += " AND project_id IS ?"
        params.append(project_id)
    if category:
        query += " AND category = ?"
        params.append(category)
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    "AUTO_SUPERSEDE_FACT_KEYS",
    "LONG_TERM_FACT_STATUSES",
    "LONG_TERM_FACT_STATUS_ACTIVE",
    "LONG_TERM_FACT_STATUS_CONFLICT_REVIEW",
    "LONG_TERM_FACT_STATUS_SUPERSEDED",
    "build_long_term_fact_metadata",
    "build_metadata_from_cache_row",
    "cache_memory_record",
    "delete_cached_memory",
    "fetch_active_long_term_fact_rows",
    "find_cached_duplicate_memory_id",
    "infer_long_term_fact_key",
    "load_long_term_cache_rows",
    "long_term_status_from_metadata",
    "normalize_fact_status",
    "normalize_string_list",
    "should_auto_supersede_fact",
]
