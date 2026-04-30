"""Search pipeline: hybrid (vector + lexical + metadata) retrieval and reranking.

Pulls together every layer of /v1/search:

- lexical_score / matched_filter_fields — small pure helpers used by the
  rerank loop and metadata-overlap detection.
- merge_search_candidate / finalize_search_result — accumulate per-candidate
  match provenance (matched_by / matched_fields / matched_terms) and emit the
  final result shape consumed by the FastAPI handler.
- rerank_results — pure scoring pass (vector weight + lexical Jaccard +
  recency + intent/focus bonuses) that produces the final ranked dedup'd
  list.
- hybrid_search — the orchestrator. Runs the vector backend search, the
  SQLite lexical/FTS pass, the task-subject branch for task_lookup intent,
  then rerank + finalize. Touches MEMORY_BACKEND.

Module-isolation contract (read tests/conftest.py):
The test suite re-imports backend/main.py via importlib.spec_from_file_location
under a synthetic module name `automem_backend_<tmp>`. That fixture instance
is NOT the canonical `backend.main`. So MEMORY_BACKEND is seeded ONLY on the
per-test instance, never on canonical backend.main. To stay compatible with
both the production single-import path and the test re-import path,
hybrid_search takes `memory_backend` as a keyword-only INJECTED parameter
(same pattern as backend.task_storage.normalize_tasks). The FastAPI handler
in main.py passes `memory_backend=get_memory_backend()` at call time, which
resolves to whichever module the request is actually running under.

Symbols still accessed via lazy `from backend import main as _main`:
- _main.normalize_text — small pure utility that still lives in main.py.
  Lazy lookup is safe here since normalize_text is env-transparent (pure
  string normalization, no MEMORY_BACKEND / TASK_DB_PATH dependence).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Optional

from backend.memory_cache import (
    LONG_TERM_FACT_STATUS_ACTIVE,
    long_term_status_from_metadata,
    normalize_fact_status,
)
from backend.search import (
    build_vector_query,
    classify_query_intent,
    is_history_query,
)
from backend.storage import _resolve_task_db_path, ensure_task_db, now_epoch
from backend.task_storage import fetch_task_search_context
from backend.tasks import task_subject_matches, task_tokens


def _normalize_text(text: str) -> str:
    """Lazy lookup of main.normalize_text to honor per-test module isolation."""
    from backend import main as _main

    return _main.normalize_text(text)


def lexical_score(query: str, text: str) -> float:
    query_tokens = task_tokens(query)
    text_tokens = task_tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens)
    union = len(query_tokens | text_tokens)
    return overlap / union if union else 0.0


def matched_filter_fields(item: dict[str, Any], filters: Optional[dict[str, Any]]) -> set[str]:
    if not filters:
        return set()
    metadata = item.get("metadata") or {}
    matched: set[str] = set()
    for field in ("project_id", "category", "domain", "task_id", "source_agent", "status"):
        expected = filters.get(field)
        if expected is None:
            continue
        actual = metadata.get(field)
        if field == "status" and str(metadata.get("domain") or "") == "long_term":
            actual = long_term_status_from_metadata(metadata)
        if _normalize_text(str(actual or "")) == _normalize_text(str(expected)):
            matched.add(field)
    return matched


def merge_search_candidate(
    by_id: dict[str, dict[str, Any]],
    item: dict[str, Any],
    *,
    matched_by: str,
    matched_fields: Optional[set[str]] = None,
    matched_terms: Optional[list[str]] = None,
) -> None:
    item_id = str(item.get("id") or "")
    if not item_id:
        return
    existing = by_id.get(item_id)
    if existing is None:
        existing = {**item}
        existing["_matched_by"] = set()
        existing["_matched_fields"] = set()
        existing["_matched_terms"] = set()
        metadata = existing.get("metadata") or {}
        existing["_status"] = long_term_status_from_metadata(metadata) if str(metadata.get("domain") or "") == "long_term" else "active"
        by_id[item_id] = existing
    else:
        existing["score"] = max(float(existing.get("score", 0.0)), float(item.get("score", 0.0)))
    existing["_matched_by"].add(matched_by)
    if matched_fields:
        existing["_matched_fields"].update(matched_fields)
    if matched_terms:
        existing["_matched_terms"].update(_normalize_text(term) for term in matched_terms if _normalize_text(term))


def finalize_search_result(item: dict[str, Any]) -> dict[str, Any]:
    matched_by = sorted(item.pop("_matched_by", set()))
    matched_fields = sorted(item.pop("_matched_fields", set()))
    matched_terms = sorted(item.pop("_matched_terms", set()))
    status = str(item.pop("_status", "active") or "active")
    result = {**item}
    result["source_memory_id"] = result.get("id")
    result["matched_by"] = matched_by
    result["matched_fields"] = matched_fields
    result["status"] = status
    metadata = result.get("metadata") or {}
    result["explainability"] = {
        "matched_by": matched_by,
        "matched_fields": matched_fields,
        "matched_terms": matched_terms,
        "source_memory_id": result.get("id"),
        "status": status,
        "fact_key": metadata.get("fact_key"),
        "valid_from": metadata.get("valid_from"),
        "valid_to": metadata.get("valid_to"),
        "supersedes": metadata.get("supersedes") or [],
        "superseded_by": metadata.get("superseded_by"),
        "conflict_status": metadata.get("conflict_status"),
        "review_status": metadata.get("review_status"),
    }
    return result


def rerank_results(query: str, items: list[dict[str, Any]], *, profile: dict[str, Any], top_k: int = 10) -> list[dict[str, Any]]:
    now = now_epoch()
    normalized_query = _normalize_text(query).lower()
    query_variants = [_normalize_text(item).lower() for item in profile.get("query_variants") or [query]]
    task_subject = _normalize_text(str(profile.get("task_subject") or "")).lower()
    reranked = []
    for item in items:
        text = item.get("memory") or item.get("text") or ""
        normalized_text = _normalize_text(text).lower()
        meta = item.get("metadata") or {}
        vector = float(item.get("score", 0.0))
        lexical = max((lexical_score(variant, text) for variant in query_variants), default=0.0)
        matched_fields = set(item.get("_matched_fields") or set())
        matched_by = set(item.get("_matched_by") or set())
        exact_bonus = 0.0
        if normalized_query and normalized_query in normalized_text:
            exact_bonus += 0.22
        if any(variant and variant in normalized_text for variant in query_variants if len(variant) >= 2):
            exact_bonus += 0.12
        recency_bonus = 0.0
        created_at = item.get("created_at")
        if created_at:
            try:
                ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).timestamp()
                age_days = max(0.0, (now - ts) / 86400)
                recency_bonus = max(0.0, 0.15 - min(age_days, 30) * 0.005)
            except Exception:
                recency_bonus = 0.0
        category = meta.get("category")
        domain = meta.get("domain")
        category_bonus = 0.0
        if category in (profile.get("preferred_categories") or set()):
            category_bonus += 0.22
        if category in (profile.get("penalized_categories") or set()):
            category_bonus -= 0.22
        if category == "next_action":
            category_bonus += 0.06
        elif category == "blocker":
            category_bonus += 0.04
        elif category in {"project_rule", "architecture_decision"}:
            category_bonus += 0.05

        domain_bonus = 0.0
        effective_domain = profile.get("effective_domain")
        if effective_domain and domain == effective_domain:
            domain_bonus = 0.18
        elif effective_domain and domain and domain != effective_domain:
            domain_bonus = -0.28

        if profile.get("intent") in {"identity_lookup", "preference_lookup", "company_lookup"}:
            final_score = vector * 0.22 + lexical * 0.38 + exact_bonus + recency_bonus * 0.5 + category_bonus + domain_bonus
        elif profile.get("intent") == "task_lookup":
            final_score = vector * 0.3 + lexical * 0.34 + exact_bonus * 0.8 + recency_bonus + category_bonus + domain_bonus
        else:
            final_score = vector * 0.4 + lexical * 0.3 + exact_bonus + recency_bonus + category_bonus + domain_bonus

        focus = profile.get("focus")
        if focus == "name":
            if re.search(r"姓名|名字|我叫|\bname\b|\bcalled\b", normalized_text):
                final_score += 0.4
            if category == "user_profile" and re.search(r"^姓名是|^名字是", normalized_text):
                final_score += 0.24
            if re.search(r"身份|角色|\brole\b|\btitle\b|ceo|cto|创始人|负责人", normalized_text, re.I):
                final_score -= 0.22
        elif focus == "role":
            if re.search(r"身份|角色|\brole\b|\btitle\b|ceo|cto|创始人|负责人", normalized_text, re.I):
                final_score += 0.28
            if re.search(r"姓名|名字|我叫|\bname\b|\bcalled\b", normalized_text):
                final_score -= 0.12
        elif focus == "language":
            if re.search(r"中文|英文|语言|沟通|\blanguage\b|\bcommunicat|\bchinese\b|\benglish\b", normalized_text):
                final_score += 0.28
            if re.search(r"总结|风格|简洁|直接|\bsummary\b|\bstyle\b|\bconcise\b|\bdirect\b", normalized_text):
                final_score -= 0.16
        elif focus == "style":
            if re.search(r"总结|风格|简洁|直接|\bsummary\b|\bstyle\b|\bconcise\b|\bdirect\b", normalized_text):
                final_score += 0.24
            if re.search(r"中文|英文|语言|沟通|\blanguage\b|\bcommunicat|\bchinese\b|\benglish\b", normalized_text):
                final_score -= 0.1
        elif focus == "company":
            if re.search(r"公司|example|团队|组织|企业|\bcompany\b|\borganization\b|\bteam\b", normalized_text):
                final_score += 0.2
        elif focus == "task" and task_subject:
            if task_subject in normalized_text:
                final_score += 0.24
            else:
                final_score -= 0.22
            if "task_title" in matched_fields:
                final_score += 0.26
            if "task_aliases" in matched_fields:
                final_score += 0.32

        if "metadata" in matched_by:
            final_score += 0.08
        if "semantic" in matched_by and "lexical" in matched_by:
            final_score += 0.04

        reranked.append({**item, "score": round(final_score, 6)})
    reranked.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in reranked:
        meta = item.get("metadata") or {}
        key = (
            _normalize_text(item.get("memory") or item.get("text") or "").lower(),
            str(meta.get("domain") or ""),
            str(meta.get("category") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= top_k:
            break
    return deduped


def hybrid_search(
    query: str,
    *,
    user_id: Optional[str],
    run_id: Optional[str],
    agent_id: Optional[str],
    filters: Optional[dict[str, Any]],
    limit: int = 10,
    include_history: bool = False,
    memory_backend: Any,
) -> dict[str, Any]:
    backend = memory_backend
    profile = classify_query_intent(query, filters)
    vector_query = build_vector_query(query, profile)
    effective_filters = dict(filters or {})
    history_mode = include_history or is_history_query(query)
    requested_status = normalize_fact_status(effective_filters.get("status"), default="") if effective_filters.get("status") else ""
    if requested_status and requested_status != LONG_TERM_FACT_STATUS_ACTIVE:
        history_mode = True
    if profile.get("effective_domain") and not effective_filters.get("domain"):
        effective_filters["domain"] = profile["effective_domain"]
    params = {
        k: v
        for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id, "filters": effective_filters or None}.items()
        if v is not None
    }
    has_identity_scope = any(value is not None for value in (user_id, run_id, agent_id))
    if has_identity_scope:
        vector_results = backend.search(query=vector_query, **params)
        raw_candidates = vector_results.get("results", [])
        candidates = []
        for item in raw_candidates:
            metadata = item.get("metadata") or {}
            item_status = long_term_status_from_metadata(metadata) if str(metadata.get("domain") or "") == "long_term" else "active"
            if effective_filters.get("project_id") and _normalize_text(str(metadata.get("project_id") or "")) != _normalize_text(
                str(effective_filters["project_id"])
            ):
                continue
            if effective_filters.get("category") and str(metadata.get("category") or "") != str(effective_filters["category"]):
                continue
            if effective_filters.get("domain") and str(metadata.get("domain") or "") != str(effective_filters["domain"]):
                continue
            if str(metadata.get("domain") or "") == "long_term":
                if requested_status and item_status != requested_status:
                    continue
                if not requested_status and not history_mode and item_status != LONG_TERM_FACT_STATUS_ACTIVE:
                    continue
            candidates.append(item)
        mode = "hybrid"
    else:
        candidates = []
        mode = "cache_only"
    by_id: dict[str, dict[str, Any]] = {}
    for item in candidates:
        filter_fields = matched_filter_fields(item, effective_filters)
        merge_search_candidate(
            by_id,
            item,
            matched_by="semantic",
            matched_fields={"text"} | filter_fields,
            matched_terms=profile.get("query_variants"),
        )
        if filter_fields:
            merge_search_candidate(
                by_id,
                item,
                matched_by="metadata",
                matched_fields=filter_fields,
            )

    query_tokens = sorted(task_tokens(query))
    query_variants = profile.get("query_variants") or [_normalize_text(query)]
    if query_tokens or query_variants:
        ensure_task_db()
        match_query = " OR ".join(query_tokens) if query_tokens else None
        sql = """
            SELECT
                c.memory_id AS id,
                c.user_id,
                c.run_id,
                c.agent_id,
                c.text AS memory,
                c.created_at,
                json_object(
                    'domain', c.domain,
                    'category', c.category,
                    'project_id', c.project_id,
                    'task_id', c.task_id,
                    'source_agent', c.source_agent,
                    'fact_key', c.fact_key,
                    'status', c.fact_status,
                    'valid_from', c.valid_from,
                    'valid_to', c.valid_to,
                    'supersedes', json(c.supersedes_json),
                    'superseded_by', c.superseded_by,
                    'conflict_status', c.conflict_status,
                    'review_status', c.review_status
                ) AS metadata_json
            FROM memory_cache c
            WHERE 1=1
        """
        sql_params: list[Any] = []
        if user_id is not None:
            sql += " AND c.user_id = ?"
            sql_params.append(user_id)
        if run_id is not None:
            sql += " AND c.run_id = ?"
            sql_params.append(run_id)
        if agent_id is not None:
            sql += " AND c.agent_id = ?"
            sql_params.append(agent_id)
        if effective_filters:
            if effective_filters.get("project_id"):
                sql += " AND c.project_id = ?"
                sql_params.append(effective_filters["project_id"])
            if effective_filters.get("category"):
                sql += " AND c.category = ?"
                sql_params.append(effective_filters["category"])
            if effective_filters.get("domain"):
                sql += " AND c.domain = ?"
                sql_params.append(effective_filters["domain"])
            if requested_status:
                sql += " AND c.fact_status = ?"
                sql_params.append(requested_status)
            elif not history_mode:
                sql += " AND (c.domain != 'long_term' OR c.fact_status = ?)"
                sql_params.append(LONG_TERM_FACT_STATUS_ACTIVE)
        variant_clauses: list[str] = []
        variant_params: list[Any] = []
        if match_query:
            variant_clauses.append("c.rowid IN (SELECT rowid FROM memory_cache_fts WHERE memory_cache_fts MATCH ?)")
            variant_params.append(match_query)
        for variant in query_variants:
            normalized_variant = _normalize_text(variant)
            if not normalized_variant:
                continue
            variant_clauses.append("c.text LIKE ?")
            variant_params.append(f"%{normalized_variant}%")
        if variant_clauses:
            sql += " AND (" + " OR ".join(variant_clauses) + ")"
            sql_params.extend(variant_params)
        sql += " ORDER BY c.updated_at DESC LIMIT 50"
        with sqlite3.connect(_resolve_task_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, sql_params).fetchall()
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            lex = max((lexical_score(variant, item.get("memory") or "") for variant in query_variants), default=0.0)
            if any(_normalize_text(variant).lower() in _normalize_text(item.get("memory") or "").lower() for variant in query_variants if _normalize_text(variant)):
                lex = max(lex, 0.65)
            if lex <= 0:
                continue
            merge_search_candidate(
                by_id,
                {**item, "score": lex},
                matched_by="lexical",
                matched_fields={"text"} | matched_filter_fields(item, effective_filters),
                matched_terms=query_variants,
            )
            filter_fields = matched_filter_fields(item, effective_filters)
            if filter_fields:
                merge_search_candidate(
                    by_id,
                    {**item, "score": lex},
                    matched_by="metadata",
                    matched_fields=filter_fields,
                )

    task_subject = _normalize_text(str(profile.get("task_subject") or ""))
    if profile.get("intent") == "task_lookup" and task_subject:
        task_context = fetch_task_search_context(
            user_id=user_id,
            project_id=effective_filters.get("project_id"),
        )
        matched_task_fields: dict[str, set[str]] = {}
        for task_id, task in task_context.items():
            fields: set[str] = set()
            if task_subject_matches(task.get("title") or "", task_subject):
                fields.add("task_title")
            aliases = [alias for alias in task.get("aliases") or [] if isinstance(alias, str)]
            if any(task_subject_matches(alias, task_subject) for alias in aliases):
                fields.add("task_aliases")
            if fields:
                matched_task_fields[task_id] = fields

        if matched_task_fields:
            placeholders = ",".join("?" for _ in matched_task_fields)
            sql = """
                SELECT
                    c.memory_id AS id,
                    c.user_id,
                    c.run_id,
                    c.agent_id,
                    c.text AS memory,
                    c.created_at,
                    json_object(
                        'domain', c.domain,
                        'category', c.category,
                        'project_id', c.project_id,
                        'task_id', c.task_id,
                        'source_agent', c.source_agent
                    ) AS metadata_json
                FROM memory_cache c
                WHERE c.task_id IN (
            """ + placeholders + ")"
            sql_params = list(matched_task_fields.keys())
            if user_id is not None:
                sql += " AND c.user_id = ?"
                sql_params.append(user_id)
            if effective_filters.get("project_id"):
                sql += " AND c.project_id = ?"
                sql_params.append(effective_filters["project_id"])
            if effective_filters.get("category"):
                sql += " AND c.category = ?"
                sql_params.append(effective_filters["category"])
            if effective_filters.get("domain"):
                sql += " AND c.domain = ?"
                sql_params.append(effective_filters["domain"])
            with sqlite3.connect(_resolve_task_db_path()) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql, sql_params).fetchall()
            for row in rows:
                item = dict(row)
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
                metadata = item.get("metadata") or {}
                match_fields = matched_task_fields.get(str(metadata.get("task_id") or ""), set())
                merge_search_candidate(
                    by_id,
                    {**item, "score": max(float(item.get("score", 0.0)), 0.72)},
                    matched_by="metadata",
                    matched_fields=set(match_fields) | matched_filter_fields(item, effective_filters),
                    matched_terms=[task_subject],
                )

    task_context = fetch_task_search_context(
        user_id=user_id,
        project_id=effective_filters.get("project_id"),
        task_ids=sorted(
            {
                str((item.get("metadata") or {}).get("task_id") or "")
                for item in by_id.values()
                if (item.get("metadata") or {}).get("task_id")
            }
        ),
    )
    for item in by_id.values():
        metadata = item.get("metadata") or {}
        task_id = str(metadata.get("task_id") or "")
        if task_id and task_id in task_context:
            item["_status"] = task_context[task_id]["status"]
        elif str(metadata.get("domain") or "") == "long_term":
            item["_status"] = long_term_status_from_metadata(metadata)
        else:
            item["_status"] = "active"
    reranked = rerank_results(query, list(by_id.values()), profile=profile, top_k=max(1, min(limit, 50)))
    if profile.get("intent") == "task_lookup" and task_subject:
        reranked = [
            item for item in reranked if task_subject_matches(item.get("memory") or item.get("text") or "", task_subject)
            or any(field in {"task_title", "task_aliases"} for field in item.get("_matched_fields", set()))
        ]
    finalized = [finalize_search_result(item) for item in reranked]
    source_counts = {"semantic": 0, "lexical": 0, "metadata": 0}
    for item in finalized:
        for source in item.get("matched_by", []):
            if source in source_counts:
                source_counts[source] += 1
    return {
        "results": finalized,
        "meta": {
            "candidate_count": len(by_id),
            "limit": max(1, min(limit, 50)),
            "mode": mode,
            "intent": profile["intent"],
            "effective_domain": profile["effective_domain"],
            "history_mode": history_mode,
            "hybrid_sources": source_counts,
        },
    }


__all__ = [
    "finalize_search_result",
    "hybrid_search",
    "lexical_score",
    "matched_filter_fields",
    "merge_search_candidate",
    "rerank_results",
]
