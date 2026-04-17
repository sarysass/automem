from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_normalize_project_ids_deduplicates_and_trims(backend_module):
    assert backend_module.normalize_project_ids([" project-a ", "", None, "project-a", "project-b"]) == [
        "project-a",
        "project-b",
    ]


def test_enforce_project_identity_defaults_single_bound_project(backend_module):
    auth = {"is_admin": False, "project_ids": ["project-alpha"]}
    assert backend_module.enforce_project_identity(auth, None) == "project-alpha"


def test_enforce_project_identity_rejects_project_outside_scope(backend_module):
    auth = {"is_admin": False, "project_ids": ["project-alpha"]}
    with pytest.raises(HTTPException, match="project_id does not match API key access scope"):
        backend_module.enforce_project_identity(auth, "project-beta")


def test_enforce_project_identity_requires_explicit_project_for_multi_scope_key(backend_module):
    auth = {"is_admin": False, "project_ids": ["project-alpha", "project-beta"]}
    with pytest.raises(HTTPException, match="project_id is required"):
        backend_module.enforce_project_identity(auth, None)


def test_enforce_payload_project_identity_mutates_project_field(backend_module):
    payload = SimpleNamespace(project_id=None)
    auth = {"is_admin": False, "project_ids": ["project-alpha"]}
    backend_module.enforce_payload_project_identity(auth, payload)
    assert payload.project_id == "project-alpha"


def test_merge_project_id_into_metadata_rejects_conflict(backend_module):
    with pytest.raises(HTTPException, match="metadata.project_id"):
        backend_module.merge_project_id_into_metadata(
            "project-alpha",
            {"domain": "long_term", "project_id": "project-beta"},
        )


def test_merge_project_id_into_filters_rejects_conflict(backend_module):
    with pytest.raises(HTTPException, match="filters.project_id"):
        backend_module.merge_project_id_into_filters(
            "project-alpha",
            {"project_id": "project-beta"},
        )


def test_ensure_memory_item_access_hides_foreign_project_item(backend_module):
    auth = {"is_admin": False, "user_id": "user-a", "project_ids": ["project-alpha"]}
    item = {
        "id": "mem_beta",
        "user_id": "user-a",
        "metadata": {"project_id": "project-beta"},
    }
    with pytest.raises(HTTPException, match="Memory not found"):
        backend_module.ensure_memory_item_access(auth, item)


def test_ensure_memory_item_access_allows_admin_bypass(backend_module):
    auth = {"is_admin": True, "user_id": None, "project_ids": []}
    item = {
        "id": "mem_beta",
        "user_id": "user-a",
        "metadata": {"project_id": "project-beta"},
    }
    assert backend_module.ensure_memory_item_access(auth, item) == item


def test_ensure_task_row_access_hides_foreign_project_row(backend_module):
    backend_module.upsert_task(
        task_id="task_beta_secret",
        user_id="user-a",
        project_id="project-beta",
        title="Beta task",
        source_agent="codex",
        last_summary="beta only",
    )
    with sqlite3.connect(backend_module.TASK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            ("task_beta_secret",),
        ).fetchone()

    auth = {"is_admin": False, "user_id": "user-a", "project_ids": ["project-alpha"]}
    with pytest.raises(HTTPException, match="Task not found"):
        backend_module.ensure_task_row_access(auth, row)


def test_ensure_task_row_access_allows_admin_bypass(backend_module):
    backend_module.upsert_task(
        task_id="task_beta_admin",
        user_id="user-a",
        project_id="project-beta",
        title="Beta task",
        source_agent="codex",
        last_summary="beta only",
    )
    with sqlite3.connect(backend_module.TASK_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT task_id, user_id, project_id, title, aliases_json, status, last_summary, source_agent, owner_agent, priority, created_at, updated_at, closed_at, archived_at FROM tasks WHERE task_id = ?",
            ("task_beta_admin",),
        ).fetchone()

    auth = {"is_admin": True, "user_id": None, "project_ids": []}
    task = backend_module.ensure_task_row_access(auth, row)
    assert task["task_id"] == "task_beta_admin"
