import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in test bootstrap
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
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

from governance import (  # noqa: F401, E402
    build_long_term_duplicate_key,  # re-export
    filter_task_memory_fields,
    should_run_offline_judge,  # re-export
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
from backend.schemas import (  # noqa: F401, E402
    AgentKeyCreateRequest,
    CacheRebuildRequest,
    ConsolidateRequest,
    GovernanceJobCreateRequest,
    GovernanceJobRunRequest,
    MemoryCreate,
    MemoryRouteRequest,
    Message,  # re-export
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
# create_agent_key + list_api_keys are re-exports for adapters using
# `from backend.main import create_agent_key`.
from backend.agent_keys import (  # noqa: F401, E402
    create_agent_key,
    list_api_keys,
    normalize_project_ids,
    seed_agent_keys,
)

# Governance jobs storage (governance_jobs table) lives in
# backend.governance_jobs. dispatch_governance_job moved to backend.services
# (re-exported below).
from backend.governance_jobs import (  # noqa: F401, E402
    GOVERNANCE_JOB_STATUS_COMPLETED,
    GOVERNANCE_JOB_STATUS_FAILED,  # re-export for services dispatch_governance_job
    claim_governance_job_by_id,
    claim_next_governance_job,
    enqueue_governance_job,
    fetch_governance_job,
    finalize_governance_job,  # re-export
    list_governance_jobs,
    release_governance_job_for_retry,  # re-export
)

# Audit log storage.
from backend.audit_log import fetch_audit_log, write_audit  # noqa: F401, E402

# HTTP auth + scope/identity enforcement.
from backend.auth import (  # noqa: F401, E402
    auth_bootstrap_bypass_enabled,
    enforce_agent_identity,
    enforce_payload_project_identity,
    enforce_project_identity,
    enforce_user_identity,
    has_usable_api_keys,
    merge_project_id_into_filters,  # re-export — test_identity_unit references via backend_module
    merge_project_id_into_metadata,  # re-export — test_identity_unit references via backend_module
    require_scope,
    verify_api_key,
)

# Memory cache table + long-term fact metadata helpers.
from backend.memory_cache import (  # noqa: F401, E402
    LONG_TERM_FACT_STATUS_ACTIVE,  # re-export
    LONG_TERM_FACT_STATUS_CONFLICT_REVIEW,  # re-export
    LONG_TERM_FACT_STATUS_SUPERSEDED,  # re-export
    build_long_term_fact_metadata,  # re-export
    build_metadata_from_cache_row,  # re-export
    cache_memory_record,  # re-export — used by tests via backend_module.cache_memory_record
    delete_cached_memory,
    fetch_active_long_term_fact_rows,  # re-export
    load_long_term_cache_rows,  # re-export
    long_term_status_from_metadata,  # re-export
    should_auto_supersede_fact,  # re-export
)


# Task domain helpers (title sanitization, materialization gate, lookup parsing).
from backend.tasks import (  # noqa: E402, F401  (re-exports for tests/backwards compat)
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

# Aggregated metrics + runtime topology (read-only, used by routers/health.py).
# Re-exported for tests/scripts that may still introspect via backend.main.
from backend.metrics import build_runtime_topology, compute_metrics  # noqa: F401, E402

# Hot-path routing extracted to backend.routing. Re-exported for tests
# and the FastAPI handlers that reference these by bare name.
from backend.routing import (  # noqa: F401, E402
    resolve_task,
    route_memory,
    task_candidate_score,
)

# Task table CRUD/query helpers extracted to backend.task_storage.
# Re-exported so handlers (list_tasks, etc.), routing.resolve_task, and
# tests that introspect backend_module.fetch_tasks keep working.
from backend.task_storage import (  # noqa: F401, E402
    decode_task_cursor,
    encode_task_cursor,
    fetch_task_ids_with_memory,
    fetch_task_search_context,
    fetch_tasks,
    fetch_tasks_page,
    hydrate_task_row,
    normalize_tasks,
    upsert_task,
)

# Search pipeline extracted to backend.search_pipeline. Re-exported for
# tests + backwards compat (some tests reference these by bare name).
from backend.search_pipeline import (  # noqa: F401, E402
    finalize_search_result,
    hybrid_search,
    lexical_score,
    matched_filter_fields,
    merge_search_candidate,
    rerank_results,
)

# Business services extracted to backend.services. Re-exported for
# tests + scripts/governance_worker.py (imports dispatch_governance_job
# via `from backend.main import dispatch_governance_job`).
from backend.services import (  # noqa: F401, E402
    archive_active_long_term_facts,
    dispatch_governance_job,
    rebuild_memory_cache,
    run_consolidation_operation,
    store_memory_with_governance,
)

# HTTP routers grouped by domain. Each module exports `router: APIRouter`
# and a `_main_module` attribute that we wire up below so handlers can read
# this main.py's CONFIG / FRONTEND_BUILD_DIR / get_memory_backend even under
# the per-test importlib.spec_from_file_location reload pattern (see
# tests/conftest.py + backend/routers/health.py docstring).
from backend.routers import admin, governance, health, memories, tasks  # noqa: E402


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


LONG_TERM_USER_CATEGORIES = {"user_profile", "preference"}
LONG_TERM_PROJECT_CATEGORIES = {"project_context", "project_rule", "architecture_decision"}
TASK_CATEGORIES = {"handoff", "progress", "blocker", "next_action"}


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


if (FRONTEND_BUILD_DIR / "assets").exists():
    app.mount("/ui/assets", StaticFiles(directory=str(FRONTEND_BUILD_DIR / "assets")), name="ui-assets")


# Wire routers to this main module instance so they can read CONFIG /
# TASK_DB_PATH / FRONTEND_BUILD_DIR / get_memory_backend / normalize_text /
# ensure_memory_item_access via request.app.state.main_module under the
# per-test importlib reload pattern (see backend/routers/health.py docstring).
app.state.main_module = sys.modules[__name__]
app.include_router(health.router)
app.include_router(memories.router)
app.include_router(tasks.router)
app.include_router(governance.router)
app.include_router(admin.router)




