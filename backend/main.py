import base64
import json
import hashlib
import logging
import os
import re
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
from fastapi.security import APIKeyHeader
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
    apply_hard_rules,
    build_long_term_duplicate_key,
    canonicalize_preference_text as governance_canonicalize_preference_text,
    classify_task_kind as governance_classify_task_kind,
    filter_task_memory_fields,
    is_query_like_long_term_text as governance_is_query_like_long_term_text,
    judge_route,
    judge_text,
    should_materialize_task as governance_should_materialize_task,
    should_run_offline_judge,
    should_store_task_memory,
)
from governance.schemas import RouteDecision, TextDecision  # noqa: E402

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
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

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
from backend.storage import (  # noqa: E402
    ensure_task_db,
    hash_token,
    now_epoch,
    utcnow_iso,
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


def strip_shared_memories(text: str) -> str:
    return normalize_text(re.sub(r"<shared-memories>.*?</shared-memories>", " ", text, flags=re.S))


def is_explicit_long_term_request(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in (
            "long term",
            "long-term",
            "长期记忆",
            "长期信息",
            "请记住",
            "记住：",
            "记录下面",
            "记住下面",
            "记住以下",
            "记录以下",
            "关键点",
        )
    )


def split_explicit_items(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    lines = [line.strip() for line in normalized.split("\n")]
    items: list[str] = []
    capture = False
    for line in lines:
        if not line:
            continue
        if is_explicit_long_term_request(line):
            capture = True
            inline = re.sub(
                r"^(?:请记住|记住|记录下面|记住下面|记住以下|记录以下|在\s*long\s*term\s*记忆中记录下面(?:两个)?关键点|长期记忆中记录下面(?:两个)?关键点)[:：]?\s*",
                "",
                line,
                flags=re.I,
            ).strip()
            if inline:
                items.append(inline)
            continue
        if re.match(r"^\d+[.)、]\s*", line) or re.match(r"^[-*•]\s*", line):
            capture = True
            item = re.sub(r"^\d+[.)、]\s*|^[-*•]\s*", "", line).strip()
            if item:
                items.append(item)
            continue
        if capture:
            items.append(line)
    return [normalize_text(item) for item in items if normalize_text(item)]


def infer_long_term_category(text: str) -> Optional[str]:
    lower = text.lower()
    if re.search(r"姓名|名字|我叫", lower):
        return "user_profile"
    if re.search(r"偏好|喜欢|我希望|优先|中文|英文|summary|简洁|direct", lower):
        return "preference"
    if re.search(r"架构|方案|决定|采用|使用|decision|architecture|backend", lower):
        return "architecture_decision"
    if re.search(r"规则|约束|必须|只能|不要|must|should|never|always|tailscale|private access", lower):
        return "project_rule"
    if re.search(r"公司|团队|内部|业务|项目|产品|workflow|memory hub|codex|openclaw", lower):
        return "project_context"
    if re.search(r"我是|身份是|ceo|cto|founder|创始人|负责人", lower):
        return "user_profile"
    return None


def is_query_like_long_term_text(text: str) -> bool:
    return governance_is_query_like_long_term_text(text)


def canonicalize_explicit_long_term_item(item: str) -> list[dict[str, str]]:
    text = normalize_text(re.sub(r"^(请记住|记住)[:：]?\s*", "", item))
    if is_query_like_long_term_text(text):
        return []
    out: list[dict[str, str]] = []

    def add(text_value: str, category: str) -> None:
        normalized = normalize_text(text_value)
        if normalized and not any(x["text"] == normalized and x["category"] == category for x in out):
            out.append({"text": normalized, "category": category})

    name_match = re.search(r"(?:我的名字叫|我叫|姓名是|名字是)\s*([^\s，,。；;]+)", text)
    if name_match:
        add(f"姓名是{name_match.group(1)}", "user_profile")

    company_match = re.search(r"(?:我的公司(?:叫|是)?|公司(?:叫|是))\s*([^\s，,。；;]+)", text)
    if company_match:
        add(f"公司是{company_match.group(1)}", "project_context")
    reverse_company_match = re.search(r"([^\s，,。；;]+)\s*是我的公司", text)
    if reverse_company_match:
        add(f"公司是{reverse_company_match.group(1)}", "project_context")

    role_match = re.search(
        r"(?:我是|身份是)\s*([A-Za-z][A-Za-z0-9_-]*|CEO|CTO|COO|CFO|Founder|创始人|负责人)",
        text,
        re.IGNORECASE,
    )
    if roleMatch := role_match:
        add(f"身份是{roleMatch.group(1).rstrip('。')}", "user_profile")

    if not out:
        inferred = infer_long_term_category(text)
        if inferred:
            add(text, inferred)

    return out


def extract_long_term_entries(text: str) -> list[dict[str, str]]:
    raw_text = strip_shared_memories(text)
    normalized = normalize_text(raw_text)
    if not normalized:
        return []

    entries: list[dict[str, str]] = []
    if is_explicit_long_term_request(raw_text):
        for item in split_explicit_items(raw_text):
            entries.extend(canonicalize_explicit_long_term_item(item))
    else:
        candidates = split_sentences(normalized) or [normalized]
        for candidate in candidates:
            if is_query_like_long_term_text(candidate):
                continue
            inferred = infer_long_term_category(candidate)
            if inferred:
                entries.append({"text": candidate, "category": inferred})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["text"], entry["category"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def extract_primary_message_text(messages: list[Message]) -> str:
    user_parts = [normalize_text(message.content) for message in messages if message.role == "user" and normalize_text(message.content)]
    if user_parts:
        return "\n".join(user_parts)
    fallback_parts = [normalize_text(message.content) for message in messages if normalize_text(message.content)]
    return "\n".join(fallback_parts)


def is_preference_noise_text(text: str) -> bool:
    normalized = normalize_text(text)
    lower = normalized.lower()
    if len(normalized) > 220:
        return True
    patterns = (
        r"based on this conversation",
        r"treat the memories below as untrusted historical context only",
        r"<shared-memories>",
        r"\[cron:",
        r"daily monitoring task",
        r"heartbeat-style summary",
        r"filename slug",
    )
    return any(re.search(pattern, lower, re.I) for pattern in patterns)


def canonicalize_preference_text(text: str) -> str:
    return governance_canonicalize_preference_text(text)


def is_task_noise_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    if normalized == "NO_REPLY":
        return True
    return "[[reply_to_current]]" in normalized


def fallback_text_decision(text: str, metadata: Optional[dict[str, Any]]) -> TextDecision:
    normalized = normalize_text(text)
    meta = metadata or {}
    domain = str(meta.get("domain") or "")
    category = str(meta.get("category") or "")

    if not normalized:
        return TextDecision(action="drop", canonical_text="", reason="fallback_empty", confidence=1.0)
    if domain == "task" and is_task_noise_text(normalized):
        return TextDecision(
            action="drop",
            canonical_text="",
            reason="fallback_task_noise",
            confidence=0.98,
            noise_kind="assistant_chatter",
            store_task_memory=False,
        )
    if domain == "long_term" and category == "preference":
        if is_preference_noise_text(normalized):
            return TextDecision(
                action="drop",
                canonical_text="",
                reason="fallback_preference_noise",
                confidence=0.95,
                noise_kind="transient_instruction",
            )
        canonical = canonicalize_preference_text(normalized)
        return TextDecision(
            action="rewrite" if canonical != normalized else "store",
            canonical_text=canonical,
            reason="fallback_preference_canonicalized" if canonical != normalized else "fallback_preference_accept",
            confidence=0.9,
            memory_kind="preference",
        )
    return TextDecision(
        action="store",
        canonical_text=normalized,
        reason="fallback_accept",
        confidence=0.6,
        memory_kind=category or infer_long_term_category(normalized),
    )


def govern_text_decision(text: str, metadata: Optional[dict[str, Any]], *, origin: str = "memory_store") -> TextDecision:
    normalized = normalize_text(text)
    hard_rule = apply_hard_rules(normalized, metadata, origin=origin)
    if hard_rule is not None:
        return hard_rule
    return judge_text(
        text=normalized,
        metadata=metadata,
        origin=origin,
        fallback=lambda: fallback_text_decision(normalized, metadata),
    )


def govern_memory_text(text: str, metadata: Optional[dict[str, Any]], *, origin: str = "memory_store") -> dict[str, Any]:
    decision = govern_text_decision(text, metadata, origin=origin)
    return {
        "action": "skip" if decision.action == "drop" else "store",
        "reason": "noise" if decision.action == "drop" and decision.noise_kind else decision.reason,
        "text": decision.canonical_text,
        "canonicalized": decision.action == "rewrite",
        "noise_kind": decision.noise_kind,
        "confidence": decision.confidence,
        "from_llm": decision.from_llm,
        "store_task_memory": decision.store_task_memory,
        "memory_kind": decision.memory_kind,
    }


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
}


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
        value = normalize_text(str(item or ""))
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def normalize_fact_status(raw: Any, *, default: str = LONG_TERM_FACT_STATUS_ACTIVE) -> str:
    value = normalize_text(str(raw or "")).lower().replace("-", "_").replace(" ", "_")
    if value in LONG_TERM_FACT_STATUSES:
        return value
    return default


def is_history_query(query: str) -> bool:
    normalized = normalize_text(query).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"(历史|之前|以前|曾经|原来|旧版本|旧记录|history|historical|previous|earlier|former)",
            normalized,
            re.I,
        )
    )


def infer_long_term_fact_key(text: str, metadata: Optional[dict[str, Any]]) -> str:
    meta = metadata or {}
    explicit = normalize_text(str(meta.get("fact_key") or ""))
    if explicit:
        return explicit
    normalized = normalize_text(text)
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
        if re.search(r"公司|company|corp|inc|llc|集团|团队", lower, re.I):
            return "project_context:company"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{category or 'long_term'}:{digest}"


def should_auto_supersede_fact(metadata: Optional[dict[str, Any]]) -> bool:
    meta = metadata or {}
    fact_key = normalize_text(str(meta.get("fact_key") or ""))
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
    merged["valid_from"] = normalize_text(str(merged.get("valid_from") or "")) or created_at
    merged["supersedes"] = normalize_string_list(supersedes if supersedes is not None else merged.get("supersedes"))

    if merged["status"] == LONG_TERM_FACT_STATUS_ACTIVE:
        merged.pop("valid_to", None)
        merged.pop("superseded_by", None)
        merged.pop("conflict_status", None)
        merged.pop("review_status", None)
        merged.pop("conflicts_with", None)
        return merged

    if merged["status"] == LONG_TERM_FACT_STATUS_SUPERSEDED:
        merged["valid_to"] = normalize_text(str(valid_to or merged.get("valid_to") or "")) or created_at
        if superseded_by:
            merged["superseded_by"] = superseded_by
        merged.pop("conflict_status", None)
        merged.pop("review_status", None)
        merged.pop("conflicts_with", None)
        return merged

    merged["conflict_status"] = normalize_text(str(conflict_status or merged.get("conflict_status") or "needs_review")) or "needs_review"
    merged["review_status"] = normalize_text(str(review_status or merged.get("review_status") or "pending")) or "pending"
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
        normalize_text(text),
        user_id or "",
        run_id or "",
        agent_id or "",
        str(meta.get("domain") or ""),
        str(meta.get("category") or ""),
        str(meta.get("project_id") or ""),
        str(meta.get("task_id") or ""),
    ]
    with sqlite3.connect(TASK_DB_PATH) as conn:
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


def looks_task_worthy(message: str, assistant_output: Optional[str]) -> bool:
    msg = strip_shared_memories(message).lower()
    assistant = strip_shared_memories(assistant_output or "").lower()

    if not msg and not assistant:
        return False
    if is_explicit_long_term_request(msg):
        return False
    if re.search(r"没有成型的 task / todo 清单|没有成型的 task/todo 清单|没有挂着的执行任务", assistant):
        return False
    if re.search(r"(当前|现在).*(执行任务|任务状态).*(什么|如何|？|\?)", msg):
        return False
    if re.search(r"请记住|记住|偏好|我喜欢|我希望|名字|姓名|公司|身份|ceo|cto", msg) and not re.search(
        r"继续|实现|修复|分析|排查|写|生成|搭建|部署|任务|流程|继续做|next action|blocker", msg
    ):
        return False
    if re.search(r"继续|实现|修复|修改|分析|排查|写|生成|搭建|部署|任务|问题|流程|继续做|shared memory|记忆系统|routing|backend|下一步|接下来", msg):
        return True
    if re.search(r"已完成|下一步|阻塞|next step|blocker|implemented|fixed|completed|updated", assistant):
        return True
    return False


def is_task_lookup_question(message: str) -> bool:
    normalized = normalize_text(message).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"(下一步|接下来|任务状态|进展|阻塞|handoff|blocker|next step|next action).*(什么|如何|吗|？|\?)",
            normalized,
            re.I,
        )
        or re.search(
            r"(什么|如何|吗|？|\?).*(下一步|接下来|任务状态|进展|阻塞|handoff|blocker|next step|next action)",
            normalized,
            re.I,
        )
    )


def extract_task_lookup_subject(message: str) -> str:
    normalized = normalize_text(message)
    if not normalized:
        return ""
    patterns = [
        r"(.+?)的下一步是什么",
        r"(.+?)接下来是什么",
        r"(.+?)的任务状态是什么",
        r"(.+?)的进展是什么",
        r"(.+?)的阻塞是什么",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        subject = normalize_text(match.group(1))
        subject = re.sub(r"^(请问|帮我看下|帮我看看|看看|告诉我)\s*", "", subject)
        if subject:
            return subject
    return ""


def task_subject_matches(text: str, subject: str) -> bool:
    normalized_text = normalize_text(text).lower()
    normalized_subject = normalize_text(subject).lower()
    if not normalized_text or not normalized_subject:
        return False
    if normalized_subject in normalized_text:
        return True
    subject_tokens = task_tokens(normalized_subject)
    if not subject_tokens:
        return False
    text_tokens = task_tokens(normalized_text)
    overlap = subject_tokens & text_tokens
    return len(overlap) >= max(1, min(2, len(subject_tokens)))


def route_memory(payload: MemoryRouteRequest) -> dict[str, Any]:
    message = strip_shared_memories(payload.message)
    assistant = strip_shared_memories(payload.assistant_output or "")
    hints = payload.client_hints or {}

    long_term_entries = extract_long_term_entries(message)
    if not long_term_entries and hints.get("explicit_long_term"):
        long_term_entries = extract_long_term_entries(assistant)

    heuristic_task_like = bool(hints.get("task_like")) or looks_task_worthy(message, assistant)

    def fallback_route_decision() -> RouteDecision:
        if long_term_entries and heuristic_task_like:
            return RouteDecision(
                route="mixed",
                reason="heuristic_mixed",
                confidence=0.72,
            )
        if long_term_entries:
            return RouteDecision(
                route="long_term",
                reason="heuristic_long_term",
                confidence=0.86,
            )
        if heuristic_task_like:
            return RouteDecision(
                route="task",
                reason="heuristic_task",
                confidence=0.68,
            )
        return RouteDecision(
            route="drop",
            reason="heuristic_drop",
            confidence=0.88,
        )

    route_decision = judge_route(
        message=message,
        assistant_output=assistant,
        hints=hints,
        long_term_entries=long_term_entries,
        task_like=heuristic_task_like,
        fallback=fallback_route_decision,
    )

    if route_decision.route in {"long_term", "mixed"} and not long_term_entries:
        fallback = fallback_route_decision()
        if fallback.route in {"long_term", "mixed"}:
            long_term_entries = extract_long_term_entries(message or assistant)

    task_result: Optional[dict[str, Any]] = None

    if route_decision.route in {"task", "mixed"}:
        resolution = resolve_task(
            TaskResolutionRequest(
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                project_id=payload.project_id,
                message=message,
                assistant_output=assistant,
                session_id=payload.session_id,
                channel=payload.channel,
            )
        )
        if resolution["action"] != "no_task":
            task_payload = TaskSummaryWriteRequest(
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                project_id=payload.project_id,
                task_id=resolution["task_id"],
                title=resolution.get("title"),
                message=message,
                assistant_output=assistant,
            )
            structured = derive_task_summary(task_payload)
            should_materialize, task_kind, _ = evaluate_task_materialization(
                task_id=resolution["task_id"],
                title=resolution.get("title"),
                payload=task_payload,
                structured=structured,
            )
            if should_materialize:
                task_result = {
                    "task_id": resolution["task_id"],
                    "title": resolution.get("title"),
                    "summary": structured,
                    "resolution": resolution,
                    "task_kind": task_kind,
                }

    if route_decision.route == "mixed" and long_term_entries and task_result:
        return {
            "route": "mixed",
            "long_term": long_term_entries,
            "task": task_result,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    if route_decision.route == "mixed" and long_term_entries:
        return {
            "route": "long_term",
            "entries": long_term_entries,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    if route_decision.route == "long_term" and long_term_entries:
        return {
            "route": "long_term",
            "entries": long_term_entries,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    if route_decision.route == "task" and task_result:
        return {
            "route": "task",
            "task": task_result,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    return {
        "route": "drop",
        "reason": route_decision.reason,
        "confidence": route_decision.confidence,
        "judge": "llm" if route_decision.from_llm else "heuristic",
    }


def task_tokens(text: str) -> set[str]:
    normalized = normalize_text(text).lower()
    stopwords = {
        "我们",
        "现在",
        "这个",
        "那个",
        "然后",
        "进行",
        "继续",
        "一下",
        "一下子",
        "task",
        "project",
        "system",
    }
    segments = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized)
    tokens: set[str] = set()
    for segment in segments:
        if not segment or segment in stopwords:
            continue
        if re.fullmatch(r"[a-z0-9]+", segment):
            if len(segment) >= 2:
                tokens.add(segment)
            continue
        if len(segment) >= 2:
            tokens.add(segment)
        max_n = min(4, len(segment))
        for n in range(2, max_n + 1):
            for index in range(0, len(segment) - n + 1):
                gram = segment[index : index + n]
                if gram and gram not in stopwords:
                    tokens.add(gram)
    return tokens


LONG_TERM_USER_CATEGORIES = {"user_profile", "preference"}
LONG_TERM_PROJECT_CATEGORIES = {"project_context", "project_rule", "architecture_decision"}
TASK_CATEGORIES = {"handoff", "progress", "blocker", "next_action"}


def _looks_project_current_state_text(text: str) -> bool:
    normalized = normalize_text(text).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"当前|现在|最近|本周|这周|下一步|接下来|进展|阻塞|handoff|blocker|workflow|正在|联调|执行状态|工作重心|主要在做",
            normalized,
            re.I,
        )
    )


def _looks_stable_or_index_text(text: str) -> bool:
    normalized = normalize_text(text).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"^公司是|^项目是|核心目标|长期约束|稳定约束|长期决策|长期边界|项目背景|项目概述|项目地图|识别信息|身份是|姓名是|名字是|偏好使用",
            normalized,
            re.I,
        )
    )


def classify_legacy_memory_scope(
    *,
    text: str,
    metadata: Optional[dict[str, Any]] = None,
    run_id: Optional[str] = None,
    clustered_project: bool = False,
) -> dict[str, str]:
    meta = metadata or {}
    category = normalize_text(str(meta.get("category") or "")).lower()
    domain = normalize_text(str(meta.get("domain") or "")).lower()
    project_id = normalize_text(str(meta.get("project_id") or ""))
    task_id = normalize_text(str(meta.get("task_id") or ""))
    normalized_run_id = normalize_text(str(run_id or ""))

    if project_id:
        return {"scope": "project", "reason": "hard:project_id"}
    if task_id or normalized_run_id:
        return {"scope": "project", "reason": "hard:task_or_run_id"}
    if domain == "task" or category in TASK_CATEGORIES:
        return {"scope": "project", "reason": "hard:task_domain"}

    if category in LONG_TERM_USER_CATEGORIES:
        return {"scope": "user_global", "reason": "semantic:user_category"}

    if category in LONG_TERM_PROJECT_CATEGORIES:
        if _looks_project_current_state_text(text):
            return {"scope": "project", "reason": "semantic:project_current_state"}
        if _looks_stable_or_index_text(text):
            return {"scope": "user_global", "reason": "semantic:project_index_or_stable_context"}

    if clustered_project and _looks_project_current_state_text(text):
        return {"scope": "project", "reason": "aux:project_cluster"}

    if _looks_stable_or_index_text(text):
        return {"scope": "user_global", "reason": "semantic:stable_or_index_text"}
    if _looks_project_current_state_text(text):
        return {"scope": "project", "reason": "semantic:current_state_text"}

    return {"scope": "migration_review", "reason": "ambiguous"}


def choose_mixed_scope_answer_roles(intent: str) -> dict[str, str]:
    if intent in {"identity_lookup", "preference_lookup", "company_lookup"}:
        return {
            "main_scope": "user_global",
            "main_role": "cross_project_preferences_and_constraints",
            "supporting_scope": "project",
            "supporting_role": "current_project_state",
        }
    if intent == "task_lookup":
        return {
            "main_scope": "project",
            "main_role": "current_project_state",
            "supporting_scope": "user_global",
            "supporting_role": "cross_project_preferences_and_constraints",
        }
    return {
        "main_scope": "user_global",
        "main_role": "cross_project_preferences_and_constraints",
        "supporting_scope": "project",
        "supporting_role": "current_project_state",
    }


def classify_query_intent(query: str, filters: Optional[dict[str, Any]]) -> dict[str, Any]:
    explicit_domain = (filters or {}).get("domain")
    normalized = normalize_text(query).lower()

    def has_any(*patterns: str) -> bool:
        return any(re.search(pattern, normalized, re.I) for pattern in patterns)

    focus = "general"
    task_subject = ""

    if explicit_domain == "task":
        intent = "task_lookup"
        focus = "task"
    elif has_any(
        r"我(的)?名字",
        r"我叫",
        r"姓名",
        r"\bname\b",
        r"user'?s name",
        r"what(?:'s| is) (?:my|the user'?s) name",
        r"\bcalled\b",
    ):
        intent = "identity_lookup"
        focus = "name"
    elif has_any(r"身份", r"我是谁", r"什么身份", r"\brole\b", r"\btitle\b", r"\bceo\b", r"\bcto\b"):
        intent = "identity_lookup"
        focus = "role"
    elif has_any(r"什么语言", r"中文", r"英文", r"沟通", r"\blanguage\b", r"\bchinese\b", r"\benglish\b", r"\bcommunicat"):
        intent = "preference_lookup"
        focus = "language"
    elif has_any(r"偏好", r"风格", r"总结", r"简洁", r"直接", r"\bpreference\b", r"\bstyle\b", r"\bsummary\b", r"\bconcise\b", r"\bdirect\b"):
        intent = "preference_lookup"
        focus = "style"
    elif has_any(r"公司", r"example", r"项目背景", r"团队", r"组织", r"企业", r"\bcompany\b", r"\bteam\b", r"\borganization\b", r"workflow", r"memory hub", r"codex", r"openclaw"):
        intent = "company_lookup"
        focus = "company"
    elif has_any(r"下一步", r"接下来", r"任务", r"进展", r"阻塞", r"handoff", r"blocker", r"next action", r"继续"):
        intent = "task_lookup"
        focus = "task"
        task_subject = extract_task_lookup_subject(query)
    else:
        intent = "generic_memory_search"

    if explicit_domain:
        effective_domain = explicit_domain
    elif intent == "task_lookup":
        effective_domain = "task"
    else:
        effective_domain = "long_term"

    preferred_categories: set[str] = set()
    exact_terms: list[str] = []
    penalized_categories: set[str] = set()

    if intent == "identity_lookup":
        preferred_categories = {"user_profile"}
        if focus == "name":
            exact_terms = ["姓名", "名字", "我叫", "称呼", "name", "user name", "called"]
        elif focus == "role":
            exact_terms = ["身份", "角色", "role", "title", "ceo", "cto", "创始人", "负责人"]
        penalized_categories = TASK_CATEGORIES
    elif intent == "preference_lookup":
        preferred_categories = {"preference"}
        if focus == "language":
            exact_terms = ["中文", "英文", "语言", "沟通", "language", "communicate", "chinese", "english"]
        else:
            exact_terms = ["偏好", "总结", "风格", "简洁", "直接", "preference", "style", "summary", "concise", "direct"]
        penalized_categories = TASK_CATEGORIES
    elif intent == "company_lookup":
        preferred_categories = {"project_context"}
        exact_terms = ["公司", "example", "项目", "团队", "组织", "企业", "company", "organization", "team"]
        penalized_categories = TASK_CATEGORIES
    elif intent == "task_lookup":
        preferred_categories = TASK_CATEGORIES
        exact_terms = ["下一步", "任务", "进展", "阻塞", "handoff", "blocker", "next", "todo"]
        if task_subject:
            exact_terms.extend(split_sentences(task_subject) or [task_subject])
        penalized_categories = LONG_TERM_USER_CATEGORIES | LONG_TERM_PROJECT_CATEGORIES
    else:
        preferred_categories = LONG_TERM_USER_CATEGORIES | LONG_TERM_PROJECT_CATEGORIES
        penalized_categories = set()

    query_variants = [normalize_text(query)]
    query_variants.extend(term for term in exact_terms if term not in query_variants)

    return {
        "intent": intent,
        "focus": focus,
        "effective_domain": effective_domain,
        "task_subject": task_subject,
        "preferred_categories": preferred_categories,
        "penalized_categories": penalized_categories,
        "query_variants": [variant for variant in query_variants if variant],
    }


def build_vector_query(query: str, profile: dict[str, Any]) -> str:
    normalized = normalize_text(query)
    variants = [normalize_text(item) for item in profile.get("query_variants") or [] if normalize_text(item)]
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        lowered = value.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        ordered.append(value)

    if normalized:
        add(normalized)

    intent = profile.get("intent")
    focus = profile.get("focus")
    if intent == "identity_lookup":
        add("user profile")
        if focus == "name":
            add("姓名 名字 我叫 称呼")
            add("name user name called")
        elif focus == "role":
            add("身份 角色 CEO 创始人")
            add("role title CEO founder")
    elif intent == "preference_lookup":
        add("user preference")
        if focus == "language":
            add("中文 英文 语言 沟通")
            add("language communicate chinese english")
        else:
            add("偏好 风格 总结 简洁 直接")
            add("preference style summary concise direct")
    elif intent == "company_lookup":
        add("project context")
        add("公司 团队 项目背景")
        add("company team organization project context")
    elif intent == "task_lookup":
        add("task progress next action")
        add("下一步 任务 进展 阻塞")
        if profile.get("task_subject"):
            add(str(profile["task_subject"]))

    for variant in variants:
        add(variant)
    return " ".join(ordered)


def derive_task_title(message: str) -> str:
    msg = normalize_text(message)
    candidates = split_sentences(message)
    if not candidates:
        return msg[:80] or "untitled-task"
    first = candidates[0]
    return first[:80]


def strip_markdown_noise(text: str) -> str:
    cleaned = re.sub(r"\[\[reply_to_current\]\]\s*", "", text)
    cleaned = re.sub(r"```(?:json)?", " ", cleaned)
    cleaned = cleaned.replace("```", " ")
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r"#+\s*", "", cleaned)
    cleaned = cleaned.replace("`", "")
    return normalize_text(cleaned)


def summarize_title_candidate(text: str, limit: int = 56) -> str:
    cleaned = strip_markdown_noise(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(查清了，)?结论先说[:：]?\s*", "", cleaned)
    cleaned = re.sub(r"^已完成[^，。]*[，,:：]\s*下一步(?:是|为)?\s*", "", cleaned)
    cleaned = re.sub(r"^如果用户需要[，,:：]\s*", "", cleaned)
    parts = split_sentences(cleaned)
    candidate = parts[0] if parts else cleaned
    return compact_text(candidate, limit) or ""


def sanitize_task_summary_preview(text: Optional[str], limit: int = 160) -> Optional[str]:
    cleaned = strip_markdown_noise(text or "")
    if not cleaned or cleaned == "NO_REPLY":
        return None
    lowered = cleaned.lower()
    if (
        ("task todo pending deadline follow-up next action" in lowered)
        or (
            "待办" in cleaned
            and "跟进" in cleaned
            and ("截止" in cleaned or "deadline" in lowered)
        )
    ):
        return "梳理待办、跟进与截止项"
    cleaned = re.sub(r"^已完成[^，。]*[，,:：]\s*下一步(?:是|为)?\s*", "", cleaned)
    cleaned = re.sub(r"^目前我这次查到的[^，。]*[，,:：]\s*", "", cleaned)
    cleaned = re.sub(r"^现在我手上[^，。]*[，,:：]\s*", "", cleaned)
    parts = split_sentences(cleaned)
    candidate = parts[0] if parts else cleaned
    candidate = candidate.strip(" -—–")
    if not candidate or candidate == "NO_REPLY":
        return None
    return compact_text(candidate, limit)


def rewrite_task_title_from_content(text: str) -> str:
    cleaned = strip_markdown_noise(text)
    lowered = cleaned.lower()
    if not cleaned:
        return ""
    if "没有成型的 task / todo 清单" in cleaned or "没有成型的 task/todo 清单" in cleaned:
        return "共享记忆任务清单核查"
    if "没有挂着的执行任务" in cleaned or "进行中的任务：没有" in cleaned:
        return "当前执行任务状态核查"
    if "opencode orphan watchdog" in lowered or "watchdog" in lowered:
        return "Mac OpenCode 孤儿进程巡检"
    if "monitor lowendtalk 214004" in lowered:
        return "LowEndTalk 214004 库存巡检"
    if "已完成的实际测试" in cleaned and ("压缩" in cleaned or "video-compress" in lowered or "simpleencoder" in lowered):
        return "视频压缩方案实测总结"
    if "共享记忆系统" in cleaned and "task resolution" in lowered and "全端" in cleaned:
        return "共享记忆系统 task resolution 中心化与全端验证"
    if "共享记忆系统" in cleaned and "task resolution" in lowered and "中心化改造" in cleaned:
        return "共享记忆系统 task resolution 中心化改造"
    if "frontend font and overflow fix completed and verified" in lowered or "frontend typography" in lowered:
        return "前端字体与溢出修复验证"
    return ""


def task_display_title(task: dict[str, Any]) -> str:
    return sanitize_task_title(
        task.get("title"),
        last_summary=task.get("last_summary"),
        task_id=task.get("task_id"),
    )


def humanize_task_id(task_id: str) -> str:
    text = re.sub(r"^task_", "", task_id)
    text = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", " ", text, flags=re.I)
    text = re.sub(r"[-_]+", " ", text)
    text = normalize_text(text)
    return compact_text(text, 56) or "untitled-task"


def rewrite_keyword_soup_title(text: str) -> str:
    lowered = normalize_text(text).lower()
    if (
        ("todo" in lowered or "待办" in lowered)
        and ("follow-up" in lowered or "follow up" in lowered or "跟进" in lowered)
        and ("deadline" in lowered or "截止" in lowered)
    ):
        return "待办任务跟进与截止项"
    return ""


def sanitize_task_title(title: Optional[str], *, last_summary: Optional[str], task_id: Optional[str]) -> str:
    raw = normalize_text(title or "")
    if raw:
        rewritten = rewrite_keyword_soup_title(raw)
        if rewritten:
            return rewritten
        content_rewrite = rewrite_task_title_from_content(raw)
        if content_rewrite:
            return content_rewrite
        cron_match = re.match(r"^\[cron:[0-9a-f-]+\s+(.*?)(?:\]\s*.*)?$", raw, re.I)
        if cron_match:
            candidate = summarize_title_candidate(cron_match.group(1))
            if candidate:
                return candidate
        looks_bad = (
            raw == "NO_REPLY"
            or raw.lower().startswith("conversation info (untrusted metadata)")
            or raw.lower().startswith("system:")
            or raw.lower().startswith("[cron:")
            or raw.lower().startswith("updated ")
            or "message_id" in raw
            or raw.startswith("{")
        )
        if not looks_bad:
            candidate = summarize_title_candidate(raw, limit=80)
            if candidate:
                return candidate

    summary_candidate = summarize_title_candidate(last_summary or "")
    content_rewrite = rewrite_task_title_from_content(last_summary or "")
    if content_rewrite:
        return content_rewrite
    if summary_candidate and summary_candidate != "NO_REPLY":
        return summary_candidate
    if task_id:
        return humanize_task_id(task_id)
    return "untitled-task"


def classify_task_kind(
    *,
    task_id: Optional[str],
    title: Optional[str],
    last_summary: Optional[str],
    source_agent: Optional[str],
    project_id: Optional[str],
) -> str:
    return governance_classify_task_kind(
        task_id=task_id,
        title=title,
        last_summary=last_summary,
        source_agent=source_agent,
        project_id=project_id,
    )


def make_task_id(title: str) -> str:
    normalized = normalize_text(title).lower()
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalized).strip("-")
    slug = slug[:48] or "task"
    return f"task_{slug}"


def split_sentences(text: str) -> list[str]:
    return [normalize_text(part) for part in re.split(r"[\n。！？!?;；]+", text) if normalize_text(part)]


def compact_text(text: Optional[str], limit: int = 240) -> Optional[str]:
    if not text:
        return None
    normalized = normalize_text(text)
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def derive_task_summary(payload: TaskSummaryWriteRequest) -> dict[str, Optional[str]]:
    message = normalize_text(payload.message or "")
    assistant = normalize_text(payload.assistant_output or "")
    summary = compact_text(payload.summary)
    progress = compact_text(payload.progress)
    blocker = compact_text(payload.blocker)
    next_action = compact_text(payload.next_action)

    if not summary:
        if assistant:
            summary = compact_text(assistant, 180)
        elif message:
            summary = compact_text(message, 180)

    if not progress and assistant and re.search(r"已完成|完成了|implemented|fixed|updated|created|done|completed", assistant, re.I):
        progress = compact_text(assistant, 220)
    if not blocker and assistant and re.search(r"阻塞|blocker|blocked", assistant, re.I):
        blocker = compact_text(assistant, 160)
    if not next_action and assistant and re.search(r"下一步|接下来|next step|next action", assistant, re.I):
        next_action = compact_text(assistant, 160)

    return {
        "summary": summary,
        "progress": progress,
        "blocker": blocker,
        "next_action": next_action,
    }


def task_has_actionable_signal(
    *,
    title: Optional[str],
    message: Optional[str],
    assistant_output: Optional[str],
    structured: dict[str, Optional[str]],
    project_id: Optional[str],
) -> bool:
    haystack = " ".join(
        part
        for part in [
            normalize_text(title or ""),
            normalize_text(message or ""),
            normalize_text(assistant_output or ""),
            *(normalize_text(value or "") for value in structured.values()),
        ]
        if part
    )
    if not haystack:
        return False
    if re.search(
        r"继续|实现|修复|修改|分析|排查|写|生成|搭建|部署|测试|重构|优化|迁移|清理|验证|跟进|推进|处理|完成|\b(fix|implement|debug|deploy|test|refactor|optimi[sz]e|migrat|clean up|verify|follow up|investigat|analy[sz]e|build|ship|complete|progress)\b",
        haystack,
        re.I,
    ):
        return True
    if project_id and any(normalize_text(value or "") for value in structured.values()):
        return True
    return any(normalize_text(value or "") for value in structured.values())


def evaluate_task_materialization(
    *,
    task_id: Optional[str],
    title: Optional[str],
    payload: TaskSummaryWriteRequest,
    structured: dict[str, Optional[str]],
) -> tuple[bool, str, str]:
    last_summary = structured.get("summary") or payload.summary
    task_kind = classify_task_kind(
        task_id=task_id,
        title=title,
        last_summary=last_summary,
        source_agent=payload.agent_id,
        project_id=payload.project_id,
    )
    if not governance_should_materialize_task(
        task_kind=task_kind,
        title=title,
        last_summary=last_summary,
    ):
        if task_kind != "work":
            return False, task_kind, f"task_kind:{task_kind}"
        return False, task_kind, "not_materializable"
    if is_task_lookup_question(payload.message or ""):
        return False, task_kind, "lookup_question"
    if not task_has_actionable_signal(
        title=title,
        message=payload.message,
        assistant_output=payload.assistant_output,
        structured=structured,
        project_id=payload.project_id,
    ):
        return False, task_kind, "not_actionable"
    return True, task_kind, "accepted"


def seed_agent_keys() -> None:
    ensure_task_db()
    if not AGENT_KEYS_JSON.strip():
        return
    try:
        payload = json.loads(AGENT_KEYS_JSON)
    except json.JSONDecodeError:
        logging.warning("Failed to parse AGENT_KEYS_JSON; skipping agent key bootstrap")
        return
    if not isinstance(payload, list):
        logging.warning("AGENT_KEYS_JSON must be a list; skipping agent key bootstrap")
        return
    now = utcnow_iso()
    with sqlite3.connect(TASK_DB_PATH) as conn:
        for item in payload:
            if not isinstance(item, dict):
                continue
            token = item.get("token")
            if not token:
                continue
            scopes = item.get("scopes") or []
            user_id = item.get("user_id")
            project_ids = normalize_project_ids(item.get("project_ids"))
            if "admin" not in scopes and not user_id:
                logging.warning(
                    "Skipping agent key bootstrap for %s because non-admin keys must declare user_id",
                    item.get("agent_id") or item.get("label") or "unknown",
                )
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO api_keys (key_id, token_hash, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    item.get("key_id") or f"key_{item.get('agent_id') or uuid.uuid4().hex[:8]}",
                    hash_token(str(token)),
                    item.get("label") or item.get("agent_id") or "agent",
                    item.get("agent_id"),
                    user_id,
                    json.dumps(project_ids, ensure_ascii=False),
                    json.dumps(scopes, ensure_ascii=False),
                    now,
                ),
            )
        conn.commit()


def create_agent_key(
    *,
    agent_id: str,
    label: str,
    scopes: list[str],
    user_id: Optional[str] = None,
    project_ids: Optional[list[str]] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    ensure_task_db()
    if "admin" not in scopes and not user_id:
        raise ValueError("Non-admin agent keys require user_id")
    normalized_project_ids = normalize_project_ids(project_ids)
    token_value = token or f"automem-agent-{uuid.uuid4().hex}"
    now = utcnow_iso()
    record = {
        "key_id": f"key_{agent_id}_{uuid.uuid4().hex[:8]}",
        "token": token_value,
        "label": label,
        "agent_id": agent_id,
        "user_id": user_id,
        "project_ids": normalized_project_ids,
        "scopes": scopes,
        "status": "active",
        "created_at": now,
    }
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO api_keys (key_id, token_hash, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                record["key_id"],
                hash_token(token_value),
                label,
                agent_id,
                user_id,
                json.dumps(normalized_project_ids, ensure_ascii=False),
                json.dumps(scopes, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
    return record


def fetch_api_key(token: str) -> Optional[dict[str, Any]]:
    ensure_task_db()
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT key_id, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at, last_used_at FROM api_keys WHERE token_hash = ?",
            (hash_token(token),),
        ).fetchone()
    if not row:
        return None
    key = dict(row)
    key["project_ids"] = json.loads(key.pop("project_ids_json") or "[]")
    key["scopes"] = json.loads(key.pop("scopes_json") or "[]")
    return key


def list_api_keys() -> list[dict[str, Any]]:
    ensure_task_db()
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key_id, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at, last_used_at FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    keys = []
    for row in rows:
        item = dict(row)
        item["project_ids"] = json.loads(item.pop("project_ids_json") or "[]")
        item["scopes"] = json.loads(item.pop("scopes_json") or "[]")
        keys.append(item)
    return keys


def normalize_project_ids(project_ids: Optional[Any]) -> list[str]:
    if not project_ids:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in project_ids:
        value = normalize_text(str(raw or ""))
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def merge_project_id_into_metadata(project_id: Optional[str], metadata: Optional[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(metadata or {})
    existing = normalize_text(str(merged.get("project_id") or ""))
    if project_id and existing and existing != project_id:
        raise HTTPException(status_code=400, detail="project_id conflicts with metadata.project_id")
    if project_id:
        merged["project_id"] = project_id
    return merged


def merge_project_id_into_filters(project_id: Optional[str], filters: Optional[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(filters or {})
    existing = normalize_text(str(merged.get("project_id") or ""))
    if project_id and existing and existing != project_id:
        raise HTTPException(status_code=400, detail="project_id conflicts with filters.project_id")
    if project_id:
        merged["project_id"] = project_id
    return merged


def auth_bootstrap_bypass_enabled() -> bool:
    return ALLOW_INSECURE_NOAUTH or "PYTEST_CURRENT_TEST" in os.environ


def has_usable_api_keys() -> bool:
    ensure_task_db()
    with sqlite3.connect(TASK_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM api_keys
            WHERE status = 'active'
              AND (
                COALESCE(user_id, '') != ''
                OR scopes_json LIKE '%"admin"%'
              )
            LIMIT 1
            """
        ).fetchone()
    return row is not None


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
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        item["detail"] = json.loads(item.pop("detail_json") or "{}")
        entries.append(item)
    return entries


def touch_api_key(key_id: str) -> None:
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
            (utcnow_iso(), key_id),
        )
        conn.commit()


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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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


def compute_metrics() -> dict[str, Any]:
    ensure_task_db()
    with sqlite3.connect(TASK_DB_PATH) as conn:
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


GOVERNANCE_JOB_STATUS_PENDING = "pending"
GOVERNANCE_JOB_STATUS_RUNNING = "running"
GOVERNANCE_JOB_STATUS_COMPLETED = "completed"
GOVERNANCE_JOB_STATUS_FAILED = "failed"
SUPPORTED_GOVERNANCE_JOB_TYPES = {"consolidate"}


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


def fetch_governance_job(job_id: str) -> Optional[dict[str, Any]]:
    ensure_task_db()
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    normalized_type = normalize_text(job_type)
    if normalized_type not in SUPPORTED_GOVERNANCE_JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported governance job type: {job_type}")
    ensure_task_db()
    now = utcnow_iso()
    normalized_key = normalize_text(idempotency_key or "") or None
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
        {normalize_text(item) for item in (job_types or []) if normalize_text(item)}
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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


def require_scope(auth: dict[str, Any], scope: str) -> None:
    if auth.get("is_admin"):
        return
    scopes = set(auth.get("scopes") or [])
    if scope not in scopes and "admin" not in scopes:
        raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")


def enforce_agent_identity(auth: dict[str, Any], agent_id: Optional[str]) -> Optional[str]:
    if auth.get("is_admin"):
        return agent_id
    key_agent_id = auth.get("agent_id")
    if agent_id and key_agent_id and agent_id != key_agent_id:
        raise HTTPException(status_code=403, detail="agent_id does not match API key identity")
    return key_agent_id or agent_id


def enforce_user_identity(auth: dict[str, Any], user_id: Optional[str]) -> Optional[str]:
    if auth.get("is_admin"):
        return user_id
    key_user_id = auth.get("user_id")
    if not key_user_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a user_id")
    if user_id and key_user_id and user_id != key_user_id:
        raise HTTPException(status_code=403, detail="user_id does not match API key identity")
    return key_user_id or user_id


def enforce_project_identity(auth: dict[str, Any], project_id: Optional[str]) -> Optional[str]:
    if auth.get("is_admin"):
        return project_id
    allowed_project_ids = normalize_project_ids(auth.get("project_ids"))
    if not allowed_project_ids:
        return project_id
    if project_id:
        if project_id not in allowed_project_ids:
            raise HTTPException(status_code=403, detail="project_id does not match API key access scope")
        return project_id
    if len(allowed_project_ids) == 1:
        return allowed_project_ids[0]
    raise HTTPException(status_code=400, detail="project_id is required for API keys bound to multiple projects")


def enforce_payload_project_identity(auth: dict[str, Any], payload: Any) -> None:
    if not hasattr(payload, "project_id"):
        return
    payload.project_id = enforce_project_identity(auth, getattr(payload, "project_id"))


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
    ensure_task_db()
    now = created_at or utcnow_iso()
    meta = dict(metadata or {})
    if str(meta.get("domain") or "") == "long_term":
        meta = build_long_term_fact_metadata(
            text=text,
            metadata=meta,
            created_at=normalize_text(str(meta.get("valid_from") or "")) or now,
            status=str(meta.get("status") or LONG_TERM_FACT_STATUS_ACTIVE),
        )
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.execute("DELETE FROM memory_cache WHERE memory_id = ?", (memory_id,))
        conn.commit()


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
    with sqlite3.connect(TASK_DB_PATH) as conn:
        stale_ids = [
            row[0]
            for row in conn.execute(query, sql_params).fetchall()
            if row[0] not in scope_ids
        ]
        if stale_ids:
            conn.executemany("DELETE FROM memory_cache WHERE memory_id = ?", [(memory_id,) for memory_id in stale_ids])
            conn.commit()
    return count


def build_metadata_from_cache_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = {
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
        with sqlite3.connect(TASK_DB_PATH) as conn:
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
            with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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


def task_candidate_score(message: str, task: dict[str, Any]) -> float:
    title = normalize_text(task.get("title") or "")
    aliases = [normalize_text(alias) for alias in task.get("aliases") or [] if alias]
    summary = normalize_text(task.get("last_summary") or "")
    haystack = " ".join(part for part in [title, *aliases, summary] if part)
    message_normalized = normalize_text(message)
    message_tokens = task_tokens(message_normalized)
    haystack_tokens = task_tokens(haystack)
    if not message_tokens or not haystack_tokens or not haystack:
        return 0.0
    overlap = len(message_tokens & haystack_tokens)
    union = len(message_tokens | haystack_tokens)
    score = overlap / union if union else 0.0

    message_lower = message_normalized.lower()
    haystack_lower = haystack.lower()
    if message_lower and message_lower in haystack_lower:
        score += 0.22
    elif title and title.lower() in message_lower:
        score += 0.18
    elif any(alias.lower() in message_lower for alias in aliases):
        score += 0.14

    if re.search(r"下一步|接下来|next step|next action", message_lower):
        if re.search(r"下一步|next action", summary.lower()):
            score += 0.14
        if re.search(r"下一步|next action", title.lower()):
            score += 0.08

    subject = extract_task_lookup_subject(message_normalized)
    if subject:
        subject_lower = subject.lower()
        if subject_lower in title.lower():
            score += 0.18
        elif any(subject_lower in alias.lower() for alias in aliases):
            score += 0.14
        elif subject_lower in summary.lower():
            score += 0.1

    return min(score, 1.0)


def resolve_task(payload: TaskResolutionRequest) -> dict[str, Any]:
    if not looks_task_worthy(payload.message, payload.assistant_output):
        return {"action": "no_task", "task_id": None, "title": None, "confidence": 0.0, "reason": "Content is not task-like"}

    lookup_question = is_task_lookup_question(payload.message)
    tasks = [task for task in fetch_tasks(payload.user_id, payload.project_id, "active") if task.get("task_kind") == "work"]
    scored = [(task_candidate_score(payload.message, task), task) for task in tasks]
    scored.sort(key=lambda item: item[0], reverse=True)

    match_threshold = 0.24 if lookup_question else 0.18
    if scored and scored[0][0] >= match_threshold:
        score, task = scored[0]
        return {
            "action": "match_existing_task",
            "task_id": task["task_id"],
            "title": task["title"],
            "confidence": round(score, 4),
            "reason": "Matched existing active task by semantic overlap",
        }

    if lookup_question:
        return {
            "action": "no_task",
            "task_id": None,
            "title": None,
            "confidence": round(scored[0][0], 4) if scored else 0.0,
            "reason": "No sufficiently relevant active task matched this lookup question",
        }

    title = derive_task_title(payload.message)
    task_id = make_task_id(title)
    structured = derive_task_summary(
        TaskSummaryWriteRequest(
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            project_id=payload.project_id,
            task_id=task_id,
            title=title,
            message=payload.message,
            assistant_output=payload.assistant_output,
        )
    )
    should_materialize, task_kind, task_reason = evaluate_task_materialization(
        task_id=task_id,
        title=title,
        payload=TaskSummaryWriteRequest(
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            project_id=payload.project_id,
            task_id=task_id,
            title=title,
            message=payload.message,
            assistant_output=payload.assistant_output,
        ),
        structured=structured,
    )
    if not should_materialize:
        return {
            "action": "no_task",
            "task_id": None,
            "title": None,
            "confidence": 0.0,
            "reason": task_reason,
            "task_kind": task_kind,
        }
    return {
        "action": "propose_new_task",
        "task_id": task_id,
        "title": title,
        "confidence": 1.0,
        "reason": "Proposed a new task from task-like content",
    }


async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    if api_key is None:
        raise HTTPException(status_code=401, detail="X-API-Key header is required")
    if ADMIN_API_KEY and secrets.compare_digest(api_key, ADMIN_API_KEY):
        return {
            "actor_type": "admin",
            "actor_label": "admin",
            "agent_id": None,
            "scopes": ["admin"],
            "is_admin": True,
        }
    key = fetch_api_key(api_key)
    if not key or key.get("status") != "active":
        raise HTTPException(status_code=401, detail="Invalid API key")
    touch_api_key(key["key_id"])
    scopes = key.get("scopes") or []
    is_admin = "admin" in scopes
    if not is_admin and not key.get("user_id"):
        raise HTTPException(status_code=403, detail="Non-admin API keys must be bound to a user_id")
    return {
        "actor_type": "agent_key",
        "actor_label": key.get("label"),
        "agent_id": key.get("agent_id"),
        "user_id": key.get("user_id"),
        "project_ids": key.get("project_ids") or [],
        "scopes": scopes,
        "is_admin": is_admin,
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
    with sqlite3.connect(TASK_DB_PATH) as conn:
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
        with sqlite3.connect(TASK_DB_PATH) as conn:
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
