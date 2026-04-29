"""SQLite storage layer for automem: schema setup, basic primitives.

Centralizing the tasks.db schema + small utilities here lets later
extractions (agent_keys, governance_jobs, audit_log) depend on this module
instead of reaching back into backend.main. backend.main re-exports every
public name so existing 'from backend.main import TASK_DB_PATH' style
imports keep working.

Concurrency: ensure_task_db enables WAL journal mode + busy_timeout=5000
so the API process and the governance worker process can both
read/write tasks.db without serializing on the rollback journal lock.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def _resolve_task_db_path() -> Path:
    """Read the tasks.db path from env on every call.

    backend.main keeps its own TASK_DB_PATH constant (re-evaluated whenever
    the test suite re-imports it via importlib.spec_from_file_location).
    storage helpers must NOT cache the path at module import time, or all
    tests would share the first test's tmp_path.
    """
    return Path(os.environ.get("TASK_DB_PATH", str(BASE_DIR / "data" / "tasks" / "tasks.db")))


def _resolve_agent_keys_json() -> str:
    return os.environ.get("AGENT_KEYS_JSON", "")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_task_db() -> None:
    db_path = _resolve_task_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        # WAL allows the API process and the governance worker process to
        # both read/write tasks.db without blocking each other on the
        # single-writer journal lock. busy_timeout retries instead of
        # raising SQLITE_BUSY immediately when contention happens.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                project_id TEXT,
                title TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                last_summary TEXT,
                source_agent TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        add_column_if_missing(conn, "tasks", "owner_agent", "TEXT")
        add_column_if_missing(conn, "tasks", "priority", "INTEGER")
        add_column_if_missing(conn, "tasks", "closed_at", "TEXT")
        add_column_if_missing(conn, "tasks", "archived_at", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_user_project_status ON tasks(user_id, project_id, status)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                agent_id TEXT,
                user_id TEXT,
                project_ids_json TEXT NOT NULL DEFAULT '[]',
                scopes_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
            """
        )
        add_column_if_missing(conn, "api_keys", "user_id", "TEXT")
        add_column_if_missing(conn, "api_keys", "project_ids_json", "TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                event_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_label TEXT,
                actor_agent_id TEXT,
                event_type TEXT NOT NULL,
                user_id TEXT,
                project_id TEXT,
                task_id TEXT,
                route TEXT,
                detail_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS governance_jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                idempotency_key TEXT UNIQUE,
                user_id TEXT,
                project_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                lease_expires_at TEXT,
                leased_by TEXT,
                started_at TEXT,
                finished_at TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        add_column_if_missing(conn, "governance_jobs", "leased_by", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_governance_jobs_status_created ON governance_jobs(status, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_governance_jobs_type_status ON governance_jobs(job_type, status)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_cache (
                memory_id TEXT PRIMARY KEY,
                user_id TEXT,
                run_id TEXT,
                agent_id TEXT,
                source_agent TEXT,
                domain TEXT,
                category TEXT,
                project_id TEXT,
                task_id TEXT,
                fact_key TEXT,
                fact_status TEXT NOT NULL DEFAULT 'active',
                valid_from TEXT,
                valid_to TEXT,
                supersedes_json TEXT NOT NULL DEFAULT '[]',
                superseded_by TEXT,
                conflict_status TEXT,
                review_status TEXT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        add_column_if_missing(conn, "memory_cache", "fact_key", "TEXT")
        add_column_if_missing(conn, "memory_cache", "fact_status", "TEXT NOT NULL DEFAULT 'active'")
        add_column_if_missing(conn, "memory_cache", "valid_from", "TEXT")
        add_column_if_missing(conn, "memory_cache", "valid_to", "TEXT")
        add_column_if_missing(conn, "memory_cache", "supersedes_json", "TEXT NOT NULL DEFAULT '[]'")
        add_column_if_missing(conn, "memory_cache", "superseded_by", "TEXT")
        add_column_if_missing(conn, "memory_cache", "conflict_status", "TEXT")
        add_column_if_missing(conn, "memory_cache", "review_status", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_cache_scope ON memory_cache(user_id, domain, project_id, category)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_cache_fact_scope ON memory_cache(user_id, domain, project_id, fact_key, fact_status)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memory_cache_fts USING fts5(text, content='memory_cache', content_rowid='rowid')"
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_cache_ai AFTER INSERT ON memory_cache BEGIN
                INSERT INTO memory_cache_fts(rowid, text) VALUES (new.rowid, new.text);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_cache_ad AFTER DELETE ON memory_cache BEGIN
                INSERT INTO memory_cache_fts(memory_cache_fts, rowid, text) VALUES('delete', old.rowid, old.text);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memory_cache_au AFTER UPDATE ON memory_cache BEGIN
                INSERT INTO memory_cache_fts(memory_cache_fts, rowid, text) VALUES('delete', old.rowid, old.text);
                INSERT INTO memory_cache_fts(rowid, text) VALUES (new.rowid, new.text);
            END
            """
        )
        conn.commit()


__all__ = [
    "BASE_DIR",
    "add_column_if_missing",
    "ensure_task_db",
    "hash_token",
    "now_epoch",
    "utcnow_iso",
]
