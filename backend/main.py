import base64
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in test bootstrap
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

BACKEND_DIR = Path(__file__).resolve().parent


def bootstrap_runtime_env() -> None:
    explicit = os.environ.get("AUTOMEM_ENV_FILE")
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(BACKEND_DIR / ".env")
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate)
            break
    os.environ.setdefault("MEM0_TELEMETRY", "False")


bootstrap_runtime_env()

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from governance import (  # noqa: E402
    build_long_term_duplicate_key,
    filter_task_memory_fields,
    should_run_offline_judge,
    should_store_task_memory,
)

try:
    from mem0 import Memory
except ImportError:  # pragma: no cover - optional in local tests
    Memory = None
try:
    from mem0.vector_stores.qdrant import Qdrant as Mem0Qdrant
except ImportError:  # pragma: no cover - optional in local tests
    Mem0Qdrant = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def patch_mem0_qdrant_indexes() -> None:
    if Mem0Qdrant is None:
        return
    disable_indexes = os.environ.get("AUTOMEM_DISABLE_QDRANT_PAYLOAD_INDEXES", "false").lower() in {"1", "true", "yes"}
    if not disable_indexes:
        return
    if getattr(Mem0Qdrant, "_automem_indexes_patched", False):
        return

    def _skip_filter_indexes(self) -> None:  # type: ignore[override]
        logger.info("Skipping mem0 Qdrant payload index creation for collection %s", self.collection_name)

    Mem0Qdrant._create_filter_indexes = _skip_filter_indexes  # type: ignore[assignment]
    Mem0Qdrant._automem_indexes_patched = True  # type: ignore[attr-defined]


patch_mem0_qdrant_indexes()

BASE_DIR = Path(__file__).resolve().parents[1]
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
# TASK_DB_PATH/AGENT_KEYS_JSON are kept as module-level constants on the
# main module so per-test importlib.spec_from_file_location reloads pick up
# fresh tmp_path values from the conftest fixture's monkeypatch.setenv.
# backend.storage helpers (ensure_task_db, etc.) read os.environ on every
# call so they work in both production (single import) and test (re-import
# per fixture) settings.
TASK_DB_PATH = Path(os.environ.get("TASK_DB_PATH", str(BASE_DIR / "data" / "tasks" / "tasks.db")))
AGENT_KEYS_JSON = os.environ.get("AGENT_KEYS_JSON", "")
DEFAULT_AGENT_ID = os.environ.get("DEFAULT_MEMORY_AGENT_ID", "agent-default")
ALLOW_INSECURE_NOAUTH = os.environ.get("AUTOMEM_ALLOW_INSECURE_NOAUTH", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

CONFIG = {
    "version": "v1.1",
    "llm": {
        "provider": "openai",
        "config": {
            "api_key": os.environ["ZAI_API_KEY"],
            "openai_base_url": os.environ["ZAI_BASE_URL"],
            "model": os.environ.get("ZAI_MODEL", "glm-4.6"),
            "temperature": 0.1,
            "max_tokens": 1000,
        },
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            "ollama_base_url": os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            "embedding_dims": int(os.environ.get("EMBEDDING_DIMS", "768")),
        },
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "host": os.environ.get("QDRANT_HOST", "127.0.0.1"),
            "port": int(os.environ.get("QDRANT_PORT", "6333")),
            "collection_name": os.environ.get("QDRANT_COLLECTION", "automem"),
            "embedding_model_dims": int(os.environ.get("EMBEDDING_DIMS", "768")),
        },
    },
    "history_db_path": os.environ.get("HISTORY_DB_PATH", str(BASE_DIR / "data" / "history" / "history.db")),
}

MEMORY_BACKEND = None
FRONTEND_SOURCE_DIR = next(
    (
        path
        for path in [
            BASE_DIR / "frontend",
            Path(__file__).resolve().parent / "frontend",
        ]
        if path.exists()
    ),
    BASE_DIR / "frontend",
)
FRONTEND_BUILD_DIR = FRONTEND_SOURCE_DIR / "dist"


# Pydantic request schemas live in backend.schemas. Re-export here so
# adapters and tests that import them via `from backend.main import X` keep
# working without churn during the main.py-split refactor.
from backend.schemas import (  # noqa: E402
    AgentKeyCreateRequest,
    CacheRebuildRequest,
    ConsolidateRequest,
    GovernanceJobCreateRequest,
    GovernanceJobRunRequest,
    MemoryCreate,
    MemoryRouteRequest,
    Message,
    SearchRequest,
    TaskLifecycleRequest,
    TaskNormalizeRequest,
    TaskResolutionRequest,
    TaskSummaryWriteRequest,
)

# Storage primitives (TASK_DB_PATH, ensure_task_db, etc.) live in
# backend.storage. Re-exported here for backward compatibility.
from backend.storage import (  # noqa: F401, E402
    _resolve_task_db_path,
    ensure_task_db,
    hash_token,  # re-exported for tests that craft fake api_keys rows
    now_epoch,
    utcnow_iso,
)

# Agent key storage (api_keys table) lives in backend.agent_keys.
from backend.agent_keys import (  # noqa: E402
    create_agent_key,
    list_api_keys,
    normalize_project_ids,
    seed_agent_keys,
)

# Governance jobs storage (governance_jobs table) lives in
# backend.governance_jobs. dispatch_governance_job stays in main.py
# because it pulls in run_consolidation_operation.
from backend.governance_jobs import (  # noqa: E402
    GOVERNANCE_JOB_STATUS_COMPLETED,
    GOVERNANCE_JOB_STATUS_FAILED,
    claim_governance_job_by_id,
    claim_next_governance_job,
    enqueue_governance_job,
    fetch_governance_job,
    finalize_governance_job,
    list_governance_jobs,
    release_governance_job_for_retry,
)

# Audit log storage.
from backend.audit_log import fetch_audit_log, write_audit  # noqa: E402

# HTTP auth + scope/identity enforcement.
from backend.auth import (  # noqa: E402
    auth_bootstrap_bypass_enabled,
    enforce_agent_identity,
    enforce_payload_project_identity,
    enforce_project_identity,
    enforce_user_identity,
    has_usable_api_keys,
    merge_project_id_into_filters,
    merge_project_id_into_metadata,
    require_scope,
    verify_api_key,
)

# Memory cache table + long-term fact metadata helpers.
from backend.memory_cache import (  # noqa: E402
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
    normalize_fact_status,
    should_auto_supersede_fact,
)


# Task domain helpers (title sanitization, materialization gate, lookup parsing).
from backend.tasks import (  # noqa: E402
    classify_task_kind,
    derive_task_summary,
    evaluate_task_materialization,
    sanitize_task_summary_preview,
    sanitize_task_title,
    task_display_title,
    task_subject_matches,
    task_tokens,
)

# Search/query intent classification + vector query builder.
from backend.search import (  # noqa: F401, E402
    build_vector_query,
    choose_mixed_scope_answer_roles,  # re-exported for backend_module test introspection
    classify_legacy_memory_scope,  # re-exported for backend_module test introspection
    classify_query_intent,
    is_history_query,
)

# Long-term memory extraction + text governance (hard-rule + LLM judge + fallback).
from backend.long_term import (  # noqa: F401, E402
    canonicalize_explicit_long_term_item,
    canonicalize_preference_text,
    extract_long_term_entries,
    extract_primary_message_text,
    fallback_text_decision,
    govern_memory_text,
    govern_text_decision,
    infer_long_term_category,
    is_explicit_long_term_request,
    is_preference_noise_text,
    is_query_like_long_term_text,
    is_task_noise_text,
    looks_task_worthy,
    split_explicit_items,
    strip_shared_memories,
)

# Aggregated metrics + runtime topology (read-only, used by /v1/metrics + /v1/healthz).
from backend.metrics import build_runtime_topology, compute_metrics  # noqa: E402

# Hot-path routing extracted to backend.routing. Re-exported for tests
# and the FastAPI handlers that reference these by bare name.
from backend.routing import (  # noqa: F401, E402
    resolve_task,
    route_memory,
    task_candidate_score,
)


def get_memory_backend():
    global MEMORY_BACKEND
    if MEMORY_BACKEND is None:
        if Memory is None:
            raise RuntimeError("memory backend package is not installed")
        MEMORY_BACKEND = Memory.from_config(CONFIG)
    return MEMORY_BACKEND


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_task_db()
    seed_agent_keys()
    if not auth_bootstrap_bypass_enabled() and not ADMIN_API_KEY and not has_usable_api_keys():
        raise RuntimeError(
            "No usable auth is configured. Set ADMIN_API_KEY, or seed at least one active API key "
            "with admin scope or a bound user_id. For local-only unsafe bootstrap, set "
            "AUTOMEM_ALLOW_INSECURE_NOAUTH=1."
        )
    yield


app = FastAPI(title="automem API", version="1.1.0", lifespan=lifespan)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def store_memory_with_governance(
    *,
    messages: list[dict[str, str]],
    user_id: Optional[str],
    run_id: Optional[str],
    agent_id: Optional[str],
    metadata: Optional[dict[str, Any]],
    infer: bool,
) -> dict[str, Any]:
    backend = get_memory_backend()
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
            if normalize_text(str(row.get("text") or "")) == normalize_text(stored_text)
        ]
        conflicting_rows = [
            row
            for row in active_rows
            if normalize_text(str(row.get("text") or "")) != normalize_text(stored_text)
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
        result = backend.add(
            messages=[{"role": "user", "content": stored_text}],
            user_id=user_id,
            run_id=run_id,
            agent_id=agent_id,
            metadata=meta,
            infer=True,
        )
        memory_id = extract_memory_id(result)
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
                    archive_active_long_term_facts(superseded_rows, superseded_by=memory_id, archived_at=now)
                except Exception:
                    backend.delete(memory_id=memory_id)
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

    result = backend.add(
        messages=[{"role": "user", "content": stored_text}],
        user_id=user_id,
        run_id=run_id,
        agent_id=agent_id,
        metadata=meta,
        infer=False,
    )
    memory_id = extract_memory_id(result)
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
                archive_active_long_term_facts(superseded_rows, superseded_by=memory_id, archived_at=now)
            except Exception:
                backend.delete(memory_id=memory_id)
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


LONG_TERM_USER_CATEGORIES = {"user_profile", "preference"}
LONG_TERM_PROJECT_CATEGORIES = {"project_context", "project_rule", "architecture_decision"}
TASK_CATEGORIES = {"handoff", "progress", "blocker", "next_action"}


def dispatch_governance_job(
    job: dict[str, Any],
    *,
    worker_id: str,
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


def ensure_task_row_access(auth: dict[str, Any], row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    if auth.get("is_admin"):
        return task
    auth_user_id = auth.get("user_id")
    if auth_user_id and task.get("user_id") != auth_user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    allowed_project_ids = normalize_project_ids(auth.get("project_ids"))
    task_project_id = normalize_text(str(task.get("project_id") or ""))
    if allowed_project_ids and task_project_id not in allowed_project_ids:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def ensure_memory_item_access(auth: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    if auth.get("is_admin"):
        return item
    auth_user_id = auth.get("user_id")
    item_user_id = item.get("user_id")
    if auth_user_id and item_user_id and item_user_id != auth_user_id:
        raise HTTPException(status_code=404, detail="Memory not found")
    allowed_project_ids = normalize_project_ids(auth.get("project_ids"))
    item_project_id = normalize_text(str((item.get("metadata") or {}).get("project_id") or ""))
    if allowed_project_ids and item_project_id not in allowed_project_ids:
        raise HTTPException(status_code=404, detail="Memory not found")
    return item


def extract_memory_id(result: Any) -> Optional[str]:
    if isinstance(result, dict):
        if result.get("id"):
            return str(result["id"])
        results = result.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict) and first.get("id"):
                return str(first["id"])
    return None


def rebuild_memory_cache(*, user_id: Optional[str], run_id: Optional[str], agent_id: Optional[str]) -> int:
    backend = get_memory_backend()
    params = {
        key: value
        for key, value in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items()
        if value is not None
    }
    raw_items = backend.get_all(**params)
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
) -> list[str]:
    backend = get_memory_backend()
    archived_history_ids: list[str] = []
    for row in rows:
        memory_id = str(row.get("memory_id") or "")
        if not memory_id:
            continue
        item = backend.get(memory_id)
        if not isinstance(item, dict):
            delete_cached_memory(memory_id)
            continue
        text = str(item.get("memory") or item.get("text") or row.get("text") or "")
        if not text:
            delete_cached_memory(memory_id)
            backend.delete(memory_id=memory_id)
            continue
        base_metadata = {
            **build_metadata_from_cache_row(row),
            **dict(item.get("metadata") or {}),
        }
        archived_metadata = build_long_term_fact_metadata(
            text=text,
            metadata=base_metadata,
            created_at=normalize_text(str(base_metadata.get("valid_from") or row.get("created_at") or archived_at)) or archived_at,
            status=LONG_TERM_FACT_STATUS_SUPERSEDED,
            superseded_by=superseded_by,
            valid_to=archived_at,
        )
        archived = backend.add(
            messages=[{"role": "user", "content": text}],
            user_id=item.get("user_id") or row.get("user_id"),
            run_id=item.get("run_id") or row.get("run_id"),
            agent_id=item.get("agent_id") or row.get("agent_id"),
            metadata=archived_metadata,
            infer=False,
        )
        archived_id = extract_memory_id(archived)
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
        backend.delete(memory_id=memory_id)
        delete_cached_memory(memory_id)
        archived_history_ids.append(archived_id)
    return archived_history_ids


def lexical_score(query: str, text: str) -> float:
    query_tokens = task_tokens(query)
    text_tokens = task_tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens)
    union = len(query_tokens | text_tokens)
    return overlap / union if union else 0.0


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
        if normalize_text(str(actual or "")) == normalize_text(str(expected)):
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
        existing["_matched_terms"].update(normalize_text(term) for term in matched_terms if normalize_text(term))


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
    normalized_query = normalize_text(query).lower()
    query_variants = [normalize_text(item).lower() for item in profile.get("query_variants") or [query]]
    task_subject = normalize_text(str(profile.get("task_subject") or "")).lower()
    reranked = []
    for item in items:
        text = item.get("memory") or item.get("text") or ""
        normalized_text = normalize_text(text).lower()
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
            normalize_text(item.get("memory") or item.get("text") or "").lower(),
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
) -> dict[str, Any]:
    backend = get_memory_backend()
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
            if effective_filters.get("project_id") and normalize_text(str(metadata.get("project_id") or "")) != normalize_text(
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
    query_variants = profile.get("query_variants") or [normalize_text(query)]
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
            normalized_variant = normalize_text(variant)
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
            if any(normalize_text(variant).lower() in normalize_text(item.get("memory") or "").lower() for variant in query_variants if normalize_text(variant)):
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

    task_subject = normalize_text(str(profile.get("task_subject") or ""))
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
) -> dict[str, int]:
    rebuilt_cache_count = 0
    if refresh_cache:
        rebuilt_cache_count = rebuild_memory_cache(user_id=user_id, run_id=None, agent_id=None)
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
                        get_memory_backend().delete(memory_id=memory_id)
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


def upsert_task(*, task_id: str, user_id: str, project_id: Optional[str], title: str, source_agent: Optional[str], last_summary: Optional[str], aliases: Optional[list[str]] = None) -> dict[str, Any]:
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


@app.get("/")
def root():
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


if (FRONTEND_BUILD_DIR / "assets").exists():
    app.mount("/ui/assets", StaticFiles(directory=str(FRONTEND_BUILD_DIR / "assets")), name="ui-assets")


@app.get("/v1/ui")
def ui_index():
    index_path = FRONTEND_BUILD_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            """
            <!doctype html>
            <html lang="zh-CN">
              <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <title>UI build missing</title>
                <style>
                  body { font-family: "Songti SC", "STSong", serif; background:#f5f2eb; color:#201c16; padding:48px; }
                  .panel { max-width:760px; margin:0 auto; background:#fbf8f2; border:1px solid #ddd4c7; border-radius:24px; padding:28px 32px; }
                  h1 { margin:0 0 12px; font-size:32px; }
                  p { margin:8px 0; line-height:1.7; }
                  code { background:#efe8dc; padding:2px 8px; border-radius:999px; }
                </style>
              </head>
              <body>
                <div class="panel">
                  <h1>前端构建产物不存在</h1>
                  <p>当前仓库还没有生成可供后端直接托管的 UI 产物。</p>
                  <p>请先在 <code>frontend/</code> 下执行 <code>npm install</code> 和 <code>npm run build</code>，再重新访问 <code>/ui</code>。</p>
                </div>
              </body>
            </html>
            """,
            status_code=503,
        )
    return FileResponse(index_path)


@app.get("/v1/healthz")
def healthz(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    return {
        "ok": True,
        "llm_model": CONFIG["llm"]["config"]["model"],
        "embed_model": CONFIG["embedder"]["config"]["model"],
        "qdrant": f"{CONFIG['vector_store']['config']['host']}:{CONFIG['vector_store']['config']['port']}",
        "task_db": str(TASK_DB_PATH),
        "runtime": build_runtime_topology(),
        "metrics": compute_metrics(),
    }


@app.get("/v1/runtime-topology")
def runtime_topology(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "metrics")
    return {"runtime": build_runtime_topology(), "metrics": compute_metrics()["governance_jobs"]}


@app.post("/v1/memories")
def add_memory(payload: MemoryCreate, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "store")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    enforce_payload_project_identity(auth, payload)
    if not any([payload.user_id, payload.agent_id, payload.run_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required")
    payload.agent_id = enforce_agent_identity(auth, payload.agent_id)
    payload.metadata = merge_project_id_into_metadata(payload.project_id, payload.metadata)
    result = store_memory_with_governance(
        messages=[m.model_dump() for m in payload.messages],
        user_id=payload.user_id,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        metadata=payload.metadata,
        infer=payload.infer,
    )
    event_type = "memory_skip" if result.get("status") == "skipped" else "memory_add"
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=payload.agent_id,
        event_type=event_type,
        user_id=payload.user_id,
        task_id=payload.run_id,
        detail={
            "metadata": payload.metadata or {},
            "infer": payload.infer,
            "status": result.get("status", "stored"),
            "reason": result.get("reason"),
            "fact_status": result.get("fact_status"),
            "fact_action": result.get("fact_action"),
            "fact_key": result.get("fact_key"),
            "superseded_memory_ids": result.get("superseded_memory_ids") or [],
            "conflicts_with": result.get("conflicts_with") or [],
        },
    )
    return result


@app.get("/v1/memories")
def get_memories(
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    project_id: Optional[str] = None,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "search")
    user_id = enforce_user_identity(auth, user_id)
    project_id = enforce_project_identity(auth, project_id)
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required")
    params = {k: v for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items() if v is not None}
    result = get_memory_backend().get_all(**params)
    if project_id is None:
        return result
    raw_items = result.get("results", []) if isinstance(result, dict) else result
    filtered = [
        item
        for item in raw_items
        if normalize_text(str((item.get("metadata") or {}).get("project_id") or "")) == project_id
    ]
    return {"results": filtered}


@app.get("/v1/memories/{memory_id}")
def get_memory(memory_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    item = get_memory_backend().get(memory_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Memory not found")
    return ensure_memory_item_access(auth, item)


@app.post("/v1/search")
def search_memories(payload: SearchRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    payload.project_id = enforce_project_identity(auth, payload.project_id)
    payload.filters = merge_project_id_into_filters(payload.project_id, payload.filters)
    result = hybrid_search(
        payload.query,
        user_id=payload.user_id,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        filters=payload.filters,
        limit=payload.limit,
        include_history=payload.include_history,
    )
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="search",
        user_id=payload.user_id,
        project_id=(payload.filters or {}).get("project_id") if payload.filters else None,
        route=None,
        detail={
            "query": payload.query,
            "meta": result.get("meta", {}),
            "top_matches": [
                {
                    "source_memory_id": item.get("source_memory_id"),
                    "matched_by": item.get("matched_by"),
                    "matched_fields": item.get("matched_fields"),
                    "status": item.get("status"),
                }
                for item in result.get("results", [])[:5]
            ],
        },
    )
    return result


@app.delete("/v1/memories/{memory_id}")
def delete_memory(memory_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "forget")
    item = get_memory_backend().get(memory_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Memory not found")
    item = ensure_memory_item_access(auth, item)
    get_memory_backend().delete(memory_id=memory_id)
    delete_cached_memory(memory_id)
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="memory_delete",
        user_id=item.get("user_id"),
        project_id=(item.get("metadata") or {}).get("project_id"),
        detail={"memory_id": memory_id},
    )
    return {"message": "deleted"}


@app.post("/v1/task-resolution")
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


@app.post("/v1/memory-route")
def memory_route(payload: MemoryRouteRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "route")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    enforce_payload_project_identity(auth, payload)
    payload.agent_id = enforce_agent_identity(auth, payload.agent_id)
    result = route_memory(payload)
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=payload.agent_id,
        event_type="memory_route",
        user_id=payload.user_id,
        project_id=payload.project_id,
        task_id=(result.get("task") or {}).get("task_id"),
        route=result.get("route"),
        detail={"message": payload.message, "reason": result.get("reason")},
    )
    return result


@app.post("/v1/task-summaries")
def task_summaries(payload: TaskSummaryWriteRequest, auth: dict[str, Any] = Depends(verify_api_key)):
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


@app.get("/v1/tasks")
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


@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
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
    task = ensure_task_row_access(auth, row)
    task["aliases"] = json.loads(task.pop("aliases_json") or "[]")
    task["title"] = task_display_title(task)
    task["display_title"] = task["title"]
    task["summary_preview"] = sanitize_task_summary_preview(task.get("last_summary"))
    return task


@app.post("/v1/tasks/{task_id}/close")
def close_task(task_id: str, payload: TaskLifecycleRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        ensure_task_row_access(auth, row)
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


@app.post("/v1/tasks/{task_id}/archive")
def archive_task(task_id: str, payload: TaskLifecycleRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "task")
    with sqlite3.connect(_resolve_task_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        ensure_task_row_access(auth, row)
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


@app.post("/v1/tasks/normalize")
def tasks_normalize(payload: TaskNormalizeRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    result = normalize_tasks(
        user_id=payload.user_id,
        project_id=payload.project_id,
        archive_non_work_active=payload.archive_non_work_active,
        prune_non_work_archived=payload.prune_non_work_archived,
        archive_work_without_memory_active=payload.archive_work_without_memory_active,
        prune_work_without_memory_archived=payload.prune_work_without_memory_archived,
        dry_run=payload.dry_run,
        refresh_cache=True,
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


@app.get("/v1/metrics")
def metrics(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "metrics")
    return {"metrics": compute_metrics()}


def run_consolidation_operation(
    payload: ConsolidateRequest,
    *,
    runtime_path: str,
    worker_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    ensure_task_db()
    rebuilt_cache_count = 0
    if payload.user_id is not None:
        rebuilt_cache_count = rebuild_memory_cache(user_id=payload.user_id, run_id=None, agent_id=None)
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
            get_memory_backend().delete(memory_id=memory_id)
            delete_cached_memory(memory_id)
        rewrite_failures: list[str] = []
        for row in rewrite_rows:
            original_memory_id = str(row["memory_id"])
            if original_memory_id in duplicate_id_set:
                continue
            metadata = row.get("fact_metadata") or build_metadata_from_cache_row(row)
            try:
                rewritten = get_memory_backend().add(
                    messages=[{"role": "user", "content": str(row["canonical_text"])}],
                    user_id=row.get("user_id"),
                    run_id=row.get("run_id"),
                    agent_id=row.get("agent_id"),
                    metadata=metadata,
                    infer=False,
                )
                rewritten_id = extract_memory_id(rewritten)
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
                get_memory_backend().delete(memory_id=original_memory_id)
                delete_cached_memory(original_memory_id)
            except Exception:
                logger.warning("Failed to rewrite canonical memory %s", original_memory_id, exc_info=True)
                rewrite_failures.append(original_memory_id)
        if rewrite_failures:
            raise RuntimeError(f"Failed to rewrite canonical memories: {rewrite_failures[:5]}")
        for memory_id in duplicate_memory_ids:
            get_memory_backend().delete(memory_id=memory_id)
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
            archive_active_long_term_facts(older_rows, superseded_by=newest_id, archived_at=utcnow_iso())

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


@app.post("/v1/consolidate")
def consolidate(payload: ConsolidateRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    result = run_consolidation_operation(payload, runtime_path="api_inline")
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="consolidate",
        detail=result,
    )
    return result


@app.post("/v1/governance/jobs")
def governance_jobs_create(payload: GovernanceJobCreateRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    payload.project_id = enforce_project_identity(auth, payload.project_id)
    if payload.job_type == "consolidate":
        consolidate_payload = ConsolidateRequest(**payload.payload)
        consolidate_payload.user_id = payload.user_id or consolidate_payload.user_id
        consolidate_payload.project_id = payload.project_id or consolidate_payload.project_id
        payload_data = consolidate_payload.model_dump()
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported governance job type: {payload.job_type}")
    job = enqueue_governance_job(
        job_type=payload.job_type,
        payload=payload_data,
        user_id=payload.user_id,
        project_id=payload.project_id,
        idempotency_key=payload.idempotency_key,
        max_attempts=payload.max_attempts,
        created_by=auth.get("actor_label") or auth.get("agent_id") or auth["actor_type"],
    )
    if payload.run_inline and job.get("status") != GOVERNANCE_JOB_STATUS_COMPLETED:
        worker_id = f"inline-{auth.get('actor_label') or auth['actor_type']}"
        claimed = claim_governance_job_by_id(
            job_id=str(job["job_id"]),
            worker_id=worker_id,
            lease_seconds=300,
        )
        if claimed and claimed["job_id"] == job["job_id"]:
            job = dispatch_governance_job(claimed, worker_id=worker_id)
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="governance_job_enqueue",
        user_id=payload.user_id,
        project_id=payload.project_id,
        detail={
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "status": job["status"],
            "idempotency_key": job.get("idempotency_key"),
            "run_inline": payload.run_inline,
            "deduplicated": job.get("deduplicated", False),
        },
    )
    return job


@app.get("/v1/governance/jobs")
def governance_jobs_list(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "admin")
    return {"jobs": list_governance_jobs(status=status, job_type=job_type, limit=limit)}


@app.get("/v1/governance/jobs/{job_id}")
def governance_jobs_get(job_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    job = fetch_governance_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Governance job not found")
    return job


@app.post("/v1/governance/jobs/run-next")
def governance_jobs_run_next(payload: GovernanceJobRunRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    worker_id = normalize_text(payload.worker_id or auth.get("agent_id") or auth.get("actor_label") or "governance-worker")
    claimed = claim_next_governance_job(
        worker_id=worker_id,
        job_types=payload.job_types,
        lease_seconds=payload.lease_seconds,
    )
    if not claimed:
        return {"status": "idle", "worker_id": worker_id}
    job = dispatch_governance_job(claimed, worker_id=worker_id)
    return {
        "status": "processed",
        "worker_id": worker_id,
        "job": job,
    }


@app.post("/v1/agent-keys")
def agent_keys_create(payload: AgentKeyCreateRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    if "admin" not in payload.scopes and not payload.user_id:
        raise HTTPException(status_code=400, detail="Non-admin API keys require user_id")
    return create_agent_key(
        agent_id=payload.agent_id,
        label=payload.label,
        scopes=payload.scopes,
        user_id=payload.user_id,
        project_ids=payload.project_ids,
        token=payload.token,
    )


@app.get("/v1/agent-keys")
def agent_keys_list(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    return {"keys": list_api_keys()}


@app.get("/v1/audit-log")
def audit_log(
    limit: int = 50,
    event_type: Optional[str] = None,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "admin")
    return {"events": fetch_audit_log(limit=limit, event_type=event_type)}


@app.post("/v1/cache/rebuild")
def cache_rebuild(payload: CacheRebuildRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    rebuilt = rebuild_memory_cache(
        user_id=payload.user_id,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
    )
    result = {
        "rebuilt": rebuilt,
        "user_id": payload.user_id,
        "run_id": payload.run_id,
        "agent_id": payload.agent_id,
    }
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="cache_rebuild",
        user_id=payload.user_id,
        detail=result,
    )
    return result
