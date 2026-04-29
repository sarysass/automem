from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


_FRONTEND_INDEX = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"
_requires_frontend_build = pytest.mark.skipif(
    not _FRONTEND_INDEX.exists(),
    reason="frontend/dist/index.html missing — build with `npm --prefix frontend run build`",
)


def add_long_term_memory(client, auth_headers, *, text: str, user_id: str, category: str = "project_context"):
    response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": text}],
            "user_id": user_id,
            "infer": False,
            "metadata": {"domain": "long_term", "category": category},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_close_task_returns_404_for_unknown_task(client, auth_headers):
    response = client.post("/v1/tasks/task_missing/close", headers=auth_headers, json={"reason": "cleanup"})
    assert response.status_code == 404


def test_archive_task_returns_404_for_unknown_task(client, auth_headers):
    response = client.post("/v1/tasks/task_missing/archive", headers=auth_headers, json={"reason": "cleanup"})
    assert response.status_code == 404


def test_missing_api_key_requires_header(client):
    response = client.get("/v1/healthz")
    assert response.status_code == 401
    assert response.json()["detail"] == "X-API-Key header is required"


def test_invalid_api_key_is_rejected(client):
    response = client.get("/v1/healthz", headers={"X-API-Key": "invalid-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_agent_keys_reject_non_admin_without_user_binding(client, auth_headers):
    response = client.post(
        "/v1/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-missing-user",
            "label": "agent missing user",
            "scopes": ["search"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Non-admin API keys require user_id"


def test_unbound_non_admin_api_key_is_rejected_at_verification(client, backend_module):
    with sqlite3.connect(backend_module.TASK_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO api_keys (key_id, token_hash, label, agent_id, user_id, project_ids_json, scopes_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                "key_unbound_agent",
                backend_module.hash_token("unbound-token"),
                "unbound agent",
                "agent-unbound",
                None,
                "[]",
                '["search"]',
                backend_module.utcnow_iso(),
            ),
        )
        conn.commit()

    response = client.get("/v1/healthz", headers={"X-API-Key": "unbound-token"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Non-admin API keys must be bound to a user_id"


def test_consolidate_respects_requested_user_scope(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-a")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-a")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-b")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-b")

    response = client.post(
        "/v1/consolidate",
        headers=auth_headers,
        json={"dry_run": True, "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["duplicate_long_term_count"] == 1
    assert payload["user_id"] == "user-a"


def test_add_memory_canonicalizes_preference_alias_and_skips_duplicate(client, auth_headers):
    english = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Prefers communication in Chinese"}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "preference"},
        },
    )
    assert english.status_code == 200, english.text
    assert english.json()["results"][0]["memory"] == "偏好使用中文沟通"

    duplicate = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "偏好使用中文沟通"}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "preference"},
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    payload = duplicate.json()
    assert payload["status"] == "skipped"
    assert payload["reason"] == "duplicate"

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    results = listed.json()["results"]
    assert [item["memory"] for item in results] == ["偏好使用中文沟通"]


def test_long_term_fact_supersedes_previous_active_fact_and_history_is_opt_in(client, auth_headers):
    first = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "偏好使用中文沟通"}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "preference"},
        },
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()

    second = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "偏好使用英文沟通"}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "preference"},
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["fact_status"] == "active"
    assert second_payload["fact_action"] == "superseded"
    assert second_payload["superseded_memory_ids"] == [first_payload["results"][0]["id"]]

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    memories = listed.json()["results"]
    assert len(memories) == 2
    by_status = {item["metadata"]["status"]: item for item in memories}
    assert by_status["active"]["memory"] == "偏好使用英文沟通"
    assert by_status["active"]["metadata"]["supersedes"] == [first_payload["results"][0]["id"]]
    assert by_status["superseded"]["memory"] == "偏好使用中文沟通"
    assert by_status["superseded"]["metadata"]["superseded_by"] == second_payload["results"][0]["id"]
    assert by_status["superseded"]["metadata"]["valid_to"]

    search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "沟通", "user_id": "user-a"},
    )
    assert search.status_code == 200, search.text
    payload = search.json()
    assert [item["status"] for item in payload["results"]] == ["active"]
    assert payload["results"][0]["memory"] == "偏好使用英文沟通"

    history = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "沟通", "user_id": "user-a", "include_history": True},
    )
    assert history.status_code == 200, history.text
    history_payload = history.json()
    assert {item["status"] for item in history_payload["results"]} == {"active", "superseded"}


def test_long_term_conflict_review_keeps_existing_active_fact(client, auth_headers):
    first = add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")

    second = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "公司是Another Corp"}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["fact_status"] == "conflict_review"
    assert second_payload["fact_action"] == "review_required"
    assert second_payload["conflicts_with"] == [first["results"][0]["id"]]

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    memories = listed.json()["results"]
    active = [item for item in memories if item["metadata"].get("status") == "active"]
    review = [item for item in memories if item["metadata"].get("status") == "conflict_review"]
    assert [item["memory"] for item in active] == ["公司是Example Corp"]
    assert [item["memory"] for item in review] == ["公司是Another Corp"]
    assert review[0]["metadata"]["conflict_status"] == "needs_review"
    assert review[0]["metadata"]["review_status"] == "pending"

    search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "公司", "user_id": "user-a"},
    )
    assert search.status_code == 200, search.text
    assert [item["memory"] for item in search.json()["results"]] == ["公司是Example Corp"]

    review_search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "Another", "user_id": "user-a", "include_history": True, "filters": {"status": "conflict_review"}},
    )
    assert review_search.status_code == 200, review_search.text
    review_payload = review_search.json()
    assert [item["memory"] for item in review_payload["results"]] == ["公司是Another Corp"]
    assert review_payload["results"][0]["status"] == "conflict_review"


def test_add_memory_rejects_task_noise_markers(client, auth_headers):
    for text in ("NO_REPLY", "[[reply_to_current]] 已完成实际测试"):
        response = client.post(
            "/v1/memories",
            headers=auth_headers,
            json={
                "messages": [{"role": "user", "content": text}],
                "user_id": "user-a",
                "run_id": "task_alpha",
                "infer": False,
                "metadata": {"domain": "task", "category": "next_action"},
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "skipped"
        assert payload["reason"] == "noise"

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a", "run_id": "task_alpha"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["results"] == []


def test_add_memory_rejects_transport_metadata_noise(client, auth_headers):
    response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": 'Conversation info (untrusted metadata): {"message_id":"1","sender":"bot"}'}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "skipped"
    assert payload["reason"] == "noise"
    assert payload["noise_kind"] == "transport_metadata"


def test_extract_long_term_entries_skips_query_like_identity_or_preference_text(backend_module):
    assert backend_module.extract_long_term_entries("我叫什么名字，我的身份是什么") == []
    assert backend_module.extract_long_term_entries("请用什么语言和我沟通") == []
    assert backend_module.extract_long_term_entries("请记住：我叫什么名字，我的身份是什么") == []


def test_memory_route_drops_time_scaffold(client, auth_headers):
    response = client.post(
        "/v1/memory-route",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-a",
            "message": "Current time: 2026-04-07 10:00 UTC+8",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["route"] == "drop"
    assert payload["reason"]


def test_memory_route_does_not_materialize_task_rows(client, auth_headers):
    response = client.post(
        "/v1/memory-route",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-a",
            "project_id": "automem-demo",
            "message": "继续修复 automem 的 task admission 问题",
            "assistant_output": "已定位到任务表污染根因，下一步是调整 admission gate。",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["route"] in {"task", "mixed"}

    tasks = client.get(
        "/v1/tasks",
        headers=auth_headers,
        params={"user_id": "user-a", "project_id": "automem-demo", "status": "active"},
    )
    assert tasks.status_code == 200, tasks.text
    assert tasks.json()["tasks"] == []


def test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise(client, auth_headers, backend_module):
    english = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "Prefers communication in Chinese"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "preference"},
    )
    backend_module.cache_memory_record(
        memory_id=english["id"],
        text="Prefers communication in Chinese",
        user_id="user-a",
        run_id=None,
        agent_id=None,
        metadata={"domain": "long_term", "category": "preference"},
    )
    duplicate = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "偏好使用中文沟通"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "preference"},
    )
    backend_module.cache_memory_record(
        memory_id=duplicate["id"],
        text="偏好使用中文沟通",
        user_id="user-a",
        run_id=None,
        agent_id=None,
        metadata={"domain": "long_term", "category": "preference"},
    )
    noise = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "NO_REPLY"}],
        user_id="user-a",
        run_id="task_alpha",
        metadata={"domain": "task", "category": "next_action", "task_id": "task_alpha"},
    )
    backend_module.cache_memory_record(
        memory_id=noise["id"],
        text="NO_REPLY",
        user_id="user-a",
        run_id="task_alpha",
        agent_id=None,
        metadata={"domain": "task", "category": "next_action", "task_id": "task_alpha"},
    )

    response = client.post(
        "/v1/consolidate",
        headers=auth_headers,
        json={"dry_run": False, "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["canonicalized_long_term_count"] == 1
    assert payload["deleted_noise_count"] == 1

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    memories = listed.json()["results"]
    assert [item["memory"] for item in memories if item["metadata"].get("category") == "preference"] == ["偏好使用中文沟通"]
    assert all(item["memory"] != "NO_REPLY" for item in memories)


def test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks(client, auth_headers, backend_module):
    for idx, text in enumerate(
        (
            "Current time: 2026-04-07 10:00 Asia/Shanghai",
            '[cron:daily] monitor lowendtalk heartbeat',
            'Conversation info (untrusted metadata): {"message_id":"m1","sender":"bot","mentions":[]}',
        ),
        start=1,
    ):
        result = backend_module.MEMORY_BACKEND.add(
            [{"role": "user", "content": text}],
            user_id="user-a",
            run_id=f"task_noise_{idx}",
            metadata={"domain": "task", "category": "handoff", "task_id": f"task_noise_{idx}"},
        )
        backend_module.cache_memory_record(
            memory_id=result["id"],
            text=text,
            user_id="user-a",
            run_id=f"task_noise_{idx}",
            agent_id=None,
            metadata={"domain": "task", "category": "handoff", "task_id": f"task_noise_{idx}"},
        )

    backend_module.upsert_task(
        task_id="task_cron-daily-monitor",
        user_id="user-a",
        project_id=None,
        title="[cron] Daily monitor",
        source_agent="agent-a",
        last_summary="[cron:daily] monitor lowendtalk",
    )

    response = client.post(
        "/v1/consolidate",
        headers=auth_headers,
        json={"dry_run": False, "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deleted_noise_count"] >= 3
    assert payload["normalized_tasks_count"] >= 1
    assert payload["task_reclassified_count"] >= 1

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    texts = [item["memory"] for item in listed.json()["results"]]
    assert not any(text.startswith("Current time:") for text in texts)
    assert not any(text.startswith("[cron:") for text in texts)
    assert not any(text.startswith("Conversation info (untrusted metadata)") for text in texts)


def test_consolidate_supersedes_legacy_active_fact_versions(client, auth_headers, backend_module):
    older = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "偏好使用中文沟通"}],
        user_id="user-a",
        metadata={
            "domain": "long_term",
            "category": "preference",
            "fact_key": "preference:language",
            "status": "active",
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
    )
    backend_module.cache_memory_record(
        memory_id=older["id"],
        text="偏好使用中文沟通",
        user_id="user-a",
        run_id=None,
        agent_id=None,
        metadata={
            "domain": "long_term",
            "category": "preference",
            "fact_key": "preference:language",
            "status": "active",
            "valid_from": "2026-01-01T00:00:00+00:00",
        },
        created_at="2026-01-01T00:00:00+00:00",
    )

    newer = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "偏好使用英文沟通"}],
        user_id="user-a",
        metadata={
            "domain": "long_term",
            "category": "preference",
            "fact_key": "preference:language",
            "status": "active",
            "valid_from": "2026-02-01T00:00:00+00:00",
        },
    )
    backend_module.cache_memory_record(
        memory_id=newer["id"],
        text="偏好使用英文沟通",
        user_id="user-a",
        run_id=None,
        agent_id=None,
        metadata={
            "domain": "long_term",
            "category": "preference",
            "fact_key": "preference:language",
            "status": "active",
            "valid_from": "2026-02-01T00:00:00+00:00",
        },
        created_at="2026-02-01T00:00:00+00:00",
    )

    response = client.post(
        "/v1/consolidate",
        headers=auth_headers,
        json={"dry_run": False, "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["superseded_fact_count"] == 1

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    memories = listed.json()["results"]
    statuses = {item["memory"]: item["metadata"]["status"] for item in memories}
    assert statuses["偏好使用英文沟通"] == "active"
    assert statuses["偏好使用中文沟通"] == "superseded"


def test_search_uses_cache_path_without_get_all(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="alpha routing policy", user_id="user-a")

    def fail_get_all(**_kwargs):
        raise AssertionError("get_all should not be used by hybrid search")

    backend_module.MEMORY_BACKEND.get_all = fail_get_all

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "routing", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["mode"] == "hybrid"
    assert len(payload["results"]) >= 1


def test_admin_search_without_identity_scope_falls_back_to_cache_only(client, auth_headers):
    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "示例用户"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["mode"] == "cache_only"


def test_identity_query_prefers_user_profile_over_task_noise(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    task_response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "下一步是检查前端管理界面"}],
            "user_id": "user-a",
            "agent_id": "openclaw-mac",
            "infer": False,
            "metadata": {"domain": "task", "category": "next_action"},
        },
    )
    assert task_response.status_code == 200, task_response.text

    original_search = backend_module.MEMORY_BACKEND.search

    def noisy_search(query: str, **params):
        results = original_search(query, **params).get("results", [])
        results.append(
            {
                "id": "task_noise",
                "memory": "下一步是检查前端管理界面",
                "text": "下一步是检查前端管理界面",
                "user_id": "user-a",
                "agent_id": "openclaw-mac",
                "metadata": {"domain": "task", "category": "next_action"},
                "created_at": "2026-01-01T00:00:00+00:00",
                "score": 0.99,
            }
        )
        return {"results": results}

    backend_module.MEMORY_BACKEND.search = noisy_search

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我的名字叫什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "identity_lookup"
    assert payload["meta"]["effective_domain"] == "long_term"
    assert payload["results"][0]["memory"] == "姓名是示例用户"


def test_name_query_prefers_name_over_role(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    add_long_term_memory(client, auth_headers, text="身份是CEO", user_id="user-a", category="user_profile")

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我的名字叫什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "identity_lookup"
    assert payload["results"][0]["memory"] == "姓名是示例用户"


def test_company_query_prefers_project_context_over_task_noise(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")
    task_response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "下一步是联系Example Corp相关站点"}],
            "user_id": "user-a",
            "agent_id": "openclaw-mac",
            "infer": False,
            "metadata": {"domain": "task", "category": "next_action"},
        },
    )
    assert task_response.status_code == 200, task_response.text

    original_search = backend_module.MEMORY_BACKEND.search

    def noisy_search(query: str, **params):
        results = original_search(query, **params).get("results", [])
        results.append(
            {
                "id": "company_task_noise",
                "memory": "下一步是联系Example Corp相关站点",
                "text": "下一步是联系Example Corp相关站点",
                "user_id": "user-a",
                "agent_id": "openclaw-mac",
                "metadata": {"domain": "task", "category": "next_action"},
                "created_at": "2026-01-01T00:00:00+00:00",
                "score": 0.98,
            }
        )
        return {"results": results}

    backend_module.MEMORY_BACKEND.search = noisy_search

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我的公司是什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "company_lookup"
    assert payload["results"][0]["memory"] == "公司是Example Corp"


def test_language_query_prefers_language_preference_over_summary_style(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="偏好使用中文沟通", user_id="user-a", category="preference")
    add_long_term_memory(client, auth_headers, text="偏好简洁直接的总结", user_id="user-a", category="preference")

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "请用什么语言和我沟通", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "preference_lookup"
    assert payload["results"][0]["memory"] == "偏好使用中文沟通"


def test_identity_query_rewrites_vector_query_for_semantic_search(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    captured: dict[str, object] = {}
    original_search = backend_module.MEMORY_BACKEND.search

    def recording_search(query: str, **params):
        captured["query"] = query
        captured["params"] = params
        return original_search(query, **params)

    backend_module.MEMORY_BACKEND.search = recording_search

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我的名字叫什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    assert "姓名" in str(captured.get("query"))
    assert "名字" in str(captured.get("query"))


def test_english_name_query_is_classified_as_identity_lookup(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    add_long_term_memory(client, auth_headers, text="身份是CEO", user_id="user-a", category="user_profile")
    captured: dict[str, object] = {}
    original_search = backend_module.MEMORY_BACKEND.search

    def recording_search(query: str, **params):
        captured["query"] = query
        return original_search(query, **params)

    backend_module.MEMORY_BACKEND.search = recording_search

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "what is the user's name", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "identity_lookup"
    assert payload["results"][0]["memory"] == "姓名是示例用户"
    assert "姓名" in str(captured.get("query"))
    assert "名字" in str(captured.get("query"))


def test_search_endpoint_accepts_larger_limit_for_candidate_expansion(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    add_long_term_memory(client, auth_headers, text="身份是CEO", user_id="user-a", category="user_profile")

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我的名字叫什么", "user_id": "user-a", "limit": 25},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["limit"] == 25
    assert len(payload["results"]) <= 25
    assert payload["results"][0]["memory"] == "姓名是示例用户"


def test_search_results_include_semantic_explainability(client, auth_headers, backend_module):
    created = add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    original_search = backend_module.MEMORY_BACKEND.search

    def semantic_search(query: str, **params):
        result = original_search(query, **params)
        result.setdefault("results", []).append(
            {
                "id": created["results"][0]["id"],
                "memory": "姓名是示例用户",
                "text": "姓名是示例用户",
                "user_id": "user-a",
                "metadata": {"domain": "long_term", "category": "user_profile"},
                "created_at": "2026-01-01T00:00:00+00:00",
                "score": 0.91,
            }
        )
        return result

    backend_module.MEMORY_BACKEND.search = semantic_search

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我的名字叫什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    top = payload["results"][0]
    assert top["source_memory_id"] == created["results"][0]["id"]
    assert "semantic" in top["matched_by"]
    assert "text" in top["matched_fields"]
    assert top["status"] == "active"
    assert top["explainability"]["source_memory_id"] == top["source_memory_id"]


def test_search_results_include_filtered_hit_explainability(client, auth_headers):
    created = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Alpha deployment checklist"}],
            "user_id": "user-a",
            "project_id": "project-alpha",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert created.status_code == 200, created.text

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={
            "query": "Alpha",
            "user_id": "user-a",
            "project_id": "project-alpha",
            "filters": {"category": "project_context"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    top = payload["results"][0]
    assert top["source_memory_id"] == created.json()["results"][0]["id"]
    assert "lexical" in top["matched_by"]
    assert "metadata" in top["matched_by"]
    assert "project_id" in top["matched_fields"]
    assert "category" in top["matched_fields"]
    assert payload["meta"]["hybrid_sources"]["metadata"] >= 1


def test_admin_search_without_user_scope_can_query_global_cache(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "Example Corp"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["mode"] in {"cache_only", "hybrid"}
    assert any(item["memory"] == "公司是Example Corp" for item in payload["results"])


def test_admin_search_without_user_scope_supports_short_chinese_keyword(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "Example"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["mode"] in {"cache_only", "hybrid"}
    assert payload["results"]
    assert payload["results"][0]["memory"] == "公司是Example Corp"


def test_task_query_defaults_to_task_domain(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")
    task_response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "下一步是检查前端管理界面"}],
            "user_id": "user-a",
            "agent_id": "openclaw-mac",
            "infer": False,
            "metadata": {"domain": "task", "category": "next_action"},
        },
    )
    assert task_response.status_code == 200, task_response.text

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "下一步是什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "task_lookup"
    assert payload["meta"]["effective_domain"] == "task"
    assert payload["results"][0]["metadata"]["category"] == "next_action"


def test_task_query_with_subject_prefers_matching_task_memory(client, auth_headers):
    generic = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "下一步是检查前端管理界面"}],
            "user_id": "user-a",
            "agent_id": "openclaw-mac",
            "infer": False,
            "metadata": {"domain": "task", "category": "next_action"},
        },
    )
    assert generic.status_code == 200, generic.text
    targeted = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "视频压缩方案遇到 OOM，下一步是降低分辨率并继续验证。"}],
            "user_id": "user-a",
            "agent_id": "openclaw-mac",
            "infer": False,
            "metadata": {"domain": "task", "category": "blocker"},
        },
    )
    assert targeted.status_code == 200, targeted.text

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "视频压缩方案的下一步是什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "task_lookup"
    assert "视频压缩" in payload["results"][0]["memory"]


def test_task_query_with_subject_returns_empty_when_no_matching_task_memory(client, auth_headers):
    generic = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "下一步是检查前端管理界面"}],
            "user_id": "user-a",
            "agent_id": "openclaw-mac",
            "infer": False,
            "metadata": {"domain": "task", "category": "next_action"},
        },
    )
    assert generic.status_code == 200, generic.text

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "视频压缩方案的下一步是什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "task_lookup"
    assert payload["results"] == []


def test_task_query_can_match_task_aliases_via_metadata(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_video_compress_alias",
        user_id="user-a",
        project_id="automem-demo",
        title="Video compression regression",
        source_agent="agent-alpha",
        last_summary="继续排查压缩链路。",
        aliases=["视频压缩方案"],
    )
    stored = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "下一步是降低分辨率并继续验证。"}],
            "user_id": "user-a",
            "run_id": "task_video_compress_alias",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "infer": False,
            "metadata": {
                "domain": "task",
                "category": "next_action",
                "task_id": "task_video_compress_alias",
                "project_id": "automem-demo",
            },
        },
    )
    assert stored.status_code == 200, stored.text

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "视频压缩方案的下一步是什么", "user_id": "user-a", "project_id": "automem-demo"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"]
    top = payload["results"][0]
    assert top["source_memory_id"] == stored.json()["results"][0]["id"]
    assert "metadata" in top["matched_by"]
    assert "task_aliases" in top["matched_fields"]
    assert top["status"] == "active"


def test_task_resolution_handles_next_step_question_against_existing_task(client, auth_headers):
    summary_response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "task_id": "task_frontend-panel",
            "title": "前端管理界面优化",
            "summary": "完成了首页布局收敛。",
            "next_action": "下一步是检查前端管理界面的搜索结果排序。",
            "message": "继续处理前端管理界面优化任务",
        },
    )
    assert summary_response.status_code == 200, summary_response.text

    resolution = client.post(
        "/v1/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "message": "前端管理界面的下一步是什么",
        },
    )
    assert resolution.status_code == 200, resolution.text
    payload = resolution.json()
    assert payload["action"] == "match_existing_task"
    assert payload["task_id"] == "task_frontend-panel"


def test_task_resolution_does_not_create_task_for_status_check_question(client, auth_headers):
    resolution = client.post(
        "/v1/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "message": "当前执行任务状态是什么",
        },
    )
    assert resolution.status_code == 200, resolution.text
    payload = resolution.json()
    assert payload["action"] == "no_task"


def test_task_resolution_avoids_false_positive_match_for_unrelated_next_step_question(client, auth_headers):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "task_id": "task_shared_memory",
            "title": "继续共享记忆系统的任务并先结合已有约束",
            "summary": "完成了回滚与 smoke 测试。",
            "next_action": "下一步是继续调优共享记忆系统的 recall 效果。",
        },
    )
    assert response.status_code == 200, response.text

    resolution = client.post(
        "/v1/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "message": "视频压缩方案的下一步是什么",
        },
    )
    assert resolution.status_code == 200, resolution.text
    payload = resolution.json()
    assert payload["action"] == "no_task"


def test_tasks_list_marks_system_and_meta_tasks(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-12345-watchdog",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    backend_module.upsert_task(
        task_id="task_conversation-info-untrusted-metadata",
        user_id="user-a",
        project_id=None,
        title="Conversation info (untrusted metadata): ...",
        source_agent="openclaw-wing",
        last_summary="[[reply_to_current]] 目前我这次查到的共享 memory里，没有成型的 task / todo 清单。",
    )

    work_task = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_automem-ui",
            "title": "优化前端管理界面",
            "summary": "完成了首页布局收敛。",
        },
    )
    assert work_task.status_code == 200, work_task.text

    response = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
    assert response.status_code == 200, response.text
    tasks = {task["task_id"]: task for task in response.json()["tasks"]}
    assert tasks["task_cron-12345-watchdog"]["task_kind"] == "system"
    assert tasks["task_conversation-info-untrusted-metadata"]["task_kind"] == "meta"
    assert tasks["task_automem-ui"]["task_kind"] == "work"


def test_question_style_task_title_is_classified_as_meta(client, auth_headers):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_共享记忆系统这个任务的下一步是什么",
            "title": "共享记忆系统这个任务的下一步是什么",
            "summary": "共享记忆系统这个任务的下一步是什么",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["action"] == "skipped"
    assert payload["reason"] == "task_kind:meta"

    tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    assert tasks == []


def test_task_status_question_title_is_classified_as_meta(client, auth_headers):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_当前执行任务状态是什么",
            "title": "当前执行任务状态是什么",
            "summary": "当前执行任务状态是什么",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["action"] == "skipped"
    assert payload["reason"] == "task_kind:meta"

    tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    assert tasks == []


def test_tasks_list_exposes_clean_display_fields(client, auth_headers):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_updated-automem-frontend-typography",
            "title": "Updated automem frontend typography to use Songti SC across the full UI,",
            "summary": "已完成 smoke 测试，下一步是检查前端管理界面。",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    task = indexed["task_updated-automem-frontend-typography"]
    assert task["display_title"] == "前端字体与溢出修复验证"
    assert task["summary_preview"] == "检查前端管理界面"


def test_tasks_list_maps_no_reply_summary_to_empty_preview(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-12345-watchdog",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )

    tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    task = indexed["task_cron-12345-watchdog"]
    assert task["display_title"] == "Mac OpenCode 孤儿进程巡检"
    assert task["summary_preview"] is None


def test_tasks_list_supports_cursor_pagination(client, auth_headers, backend_module):
    for task_id in ("task_archived_a", "task_archived_b", "task_archived_c"):
        backend_module.upsert_task(
            task_id=task_id,
            user_id="user-a",
            project_id="automem-demo",
            title=f"{task_id} title",
            source_agent="codex",
            last_summary=f"{task_id} summary",
        )
        archived = client.post(f"/v1/tasks/{task_id}/archive", headers=auth_headers, json={"reason": "pagination"})
        assert archived.status_code == 200, archived.text

    with sqlite3.connect(backend_module.TASK_DB_PATH) as conn:
        conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", ("2026-04-08T03:00:00+00:00", "task_archived_a"))
        conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", ("2026-04-08T02:00:00+00:00", "task_archived_b"))
        conn.execute("UPDATE tasks SET updated_at = ? WHERE task_id = ?", ("2026-04-08T01:00:00+00:00", "task_archived_c"))
        conn.commit()

    first = client.get(
        "/v1/tasks",
        headers=auth_headers,
        params={"user_id": "user-a", "status": "archived", "limit": 2},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert [task["task_id"] for task in first_payload["tasks"]] == ["task_archived_a", "task_archived_b"]
    assert first_payload["page_info"]["has_more"] is True
    assert first_payload["page_info"]["next_cursor"]

    second = client.get(
        "/v1/tasks",
        headers=auth_headers,
        params={
            "user_id": "user-a",
            "status": "archived",
            "limit": 2,
            "cursor": first_payload["page_info"]["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert [task["task_id"] for task in second_payload["tasks"]] == ["task_archived_c"]
    assert second_payload["page_info"]["has_more"] is False
    assert second_payload["page_info"]["next_cursor"] is None


def test_tasks_list_rewrites_task_resolution_titles_and_keyword_soup_preview(client, auth_headers):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_task-resolution-centralization",
            "title": "继续完成共享记忆系统的中心化 task resolution 改造并做全端部署验证",
            "summary": "task todo pending deadline follow-up next action 待办 任务 跟进 截止",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    task = indexed["task_task-resolution-centralization"]
    assert task["display_title"] == "共享记忆系统 task resolution 中心化与全端验证"
    assert task["summary_preview"] == "梳理待办、跟进与截止项"


def test_task_normalize_archives_non_work_items_and_rewrites_titles(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-12345-watchdog",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    backend_module.upsert_task(
        task_id="task_当前执行任务状态是什么",
        user_id="user-a",
        project_id=None,
        title="当前执行任务状态是什么",
        source_agent="codex",
        last_summary="当前执行任务状态是什么",
    )
    client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_work_clean",
            "title": "优化前端管理界面",
            "summary": "完成了首页布局收敛。",
        },
    )

    response = client.post(
        "/v1/tasks/normalize",
        headers=auth_headers,
        json={"user_id": "user-a", "archive_non_work_active": True, "dry_run": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["archived_tasks"] >= 2

    active = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    active_ids = {task["task_id"] for task in active}
    assert "task_work_clean" in active_ids
    assert "task_cron-12345-watchdog" not in active_ids
    assert "task_当前执行任务状态是什么" not in active_ids

    archived = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "archived"}).json()["tasks"]
    archived_index = {task["task_id"]: task for task in archived}
    assert archived_index["task_cron-12345-watchdog"]["title"] == "Mac OpenCode 孤儿进程巡检"


def test_task_normalize_can_prune_archived_non_work_tasks_and_memory(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-prune-me",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    archived = client.post("/v1/tasks/task_cron-prune-me/archive", headers=auth_headers, json={"reason": "cleanup"})
    assert archived.status_code == 200, archived.text

    task_memory = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "NO_REPLY"}],
        user_id="user-a",
        run_id="task_cron-prune-me",
        metadata={"domain": "task", "category": "handoff", "task_id": "task_cron-prune-me"},
    )
    backend_module.cache_memory_record(
        memory_id=task_memory["id"],
        text="NO_REPLY",
        user_id="user-a",
        run_id="task_cron-prune-me",
        agent_id="openclaw-ring",
        metadata={"domain": "task", "category": "handoff", "task_id": "task_cron-prune-me"},
    )

    response = client.post(
        "/v1/tasks/normalize",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "archive_non_work_active": False,
            "prune_non_work_archived": True,
            "dry_run": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deleted_archived_non_work_tasks"] >= 1
    assert payload["deleted_archived_non_work_memory"] >= 1

    archived_tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "archived"}).json()["tasks"]
    assert "task_cron-prune-me" not in {task["task_id"] for task in archived_tasks}

    memories = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a", "run_id": "task_cron-prune-me"}).json()["results"]
    assert memories == []


def test_task_normalize_prune_keeps_task_when_memory_delete_fails(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-prune-fails",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    archived = client.post("/v1/tasks/task_cron-prune-fails/archive", headers=auth_headers, json={"reason": "cleanup"})
    assert archived.status_code == 200, archived.text

    task_memory = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "NO_REPLY"}],
        user_id="user-a",
        run_id="task_cron-prune-fails",
        metadata={"domain": "task", "category": "handoff", "task_id": "task_cron-prune-fails"},
    )
    backend_module.cache_memory_record(
        memory_id=task_memory["id"],
        text="NO_REPLY",
        user_id="user-a",
        run_id="task_cron-prune-fails",
        agent_id="openclaw-ring",
        metadata={"domain": "task", "category": "handoff", "task_id": "task_cron-prune-fails"},
    )

    original_delete = backend_module.MEMORY_BACKEND.delete

    def failing_delete(*, memory_id):
        raise RuntimeError(f"cannot delete {memory_id}")

    backend_module.MEMORY_BACKEND.delete = failing_delete
    with pytest.raises(RuntimeError, match="Failed to delete archived non-work task memories"):
        client.post(
            "/v1/tasks/normalize",
            headers=auth_headers,
            json={
                "user_id": "user-a",
                "archive_non_work_active": False,
                "prune_non_work_archived": True,
                "dry_run": False,
            },
        )
    backend_module.MEMORY_BACKEND.delete = original_delete

    archived_tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "archived"}).json()["tasks"]
    assert "task_cron-prune-fails" in {task["task_id"] for task in archived_tasks}

    memories = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a", "run_id": "task_cron-prune-fails"}).json()["results"]
    assert memories


def test_task_normalize_archives_and_prunes_work_tasks_without_task_memory(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_orphan_active",
        user_id="user-a",
        project_id="automem-demo",
        title="优化共享记忆任务清理",
        source_agent="codex",
        last_summary="完成了第一轮分析。",
    )
    backend_module.upsert_task(
        task_id="task_orphan_archived",
        user_id="user-a",
        project_id="automem-demo",
        title="补充共享记忆治理说明",
        source_agent="codex",
        last_summary="整理文档摘要。",
    )
    archived = client.post("/v1/tasks/task_orphan_archived/archive", headers=auth_headers, json={"reason": "cleanup"})
    assert archived.status_code == 200, archived.text

    with_memory = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_backed_by_memory",
            "title": "实现任务治理修复",
            "summary": "完成了任务治理修复。",
        },
    )
    assert with_memory.status_code == 200, with_memory.text

    response = client.post(
        "/v1/tasks/normalize",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "project_id": "automem-demo",
            "archive_non_work_active": False,
            "prune_non_work_archived": False,
            "archive_work_without_memory_active": True,
            "prune_work_without_memory_archived": True,
            "dry_run": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["active_work_without_memory_detected"] >= 1
    assert payload["archived_work_without_memory_detected"] >= 1
    assert payload["archived_work_without_memory_tasks"] >= 1
    assert payload["deleted_archived_work_without_memory_tasks"] >= 1

    active = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    active_ids = {task["task_id"] for task in active}
    assert "task_orphan_active" not in active_ids
    assert "task_backed_by_memory" in active_ids

    archived_tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "archived"}).json()["tasks"]
    archived_ids = {task["task_id"] for task in archived_tasks}
    assert "task_orphan_active" in archived_ids
    assert "task_orphan_archived" not in archived_ids


def test_agent_key_enforces_bound_agent_identity(client, auth_headers):
    key_response = client.post(
        "/v1/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-alpha",
            "label": "agent alpha",
            "scopes": ["store", "search", "route", "task", "metrics"],
            "user_id": "user-a",
        },
    )
    assert key_response.status_code == 200, key_response.text
    token = key_response.json()["token"]

    mismatch = client.post(
        "/v1/memories",
        headers={"X-API-Key": token},
        json={
            "messages": [{"role": "user", "content": "alpha"}],
            "user_id": "user-a",
            "agent_id": "agent-beta",
            "metadata": {"domain": "long_term", "category": "project_context"},
            "infer": False,
        },
    )
    assert mismatch.status_code == 403

    ok = client.post(
        "/v1/memories",
        headers={"X-API-Key": token},
        json={
            "messages": [{"role": "user", "content": "alpha"}],
            "metadata": {"domain": "long_term", "category": "project_context"},
            "infer": False,
        },
    )
    assert ok.status_code == 200, ok.text


def test_agent_key_search_is_bound_to_declared_user(client, auth_headers):
    key_response = client.post(
        "/v1/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-alpha",
            "label": "agent alpha",
            "scopes": ["search"],
            "user_id": "user-a",
        },
    )
    assert key_response.status_code == 200, key_response.text
    token = key_response.json()["token"]

    mismatch = client.post(
        "/v1/search",
        headers={"X-API-Key": token},
        json={"query": "alpha", "user_id": "user-b"},
    )
    assert mismatch.status_code == 403


def test_task_summaries_store_each_field_as_memory_message(client, auth_headers, backend_module):
    captured: list[dict[str, object]] = []
    original_add = backend_module.MEMORY_BACKEND.add

    def recording_add(*, messages, **kwargs):
        captured.append({"messages": messages, **kwargs})
        return original_add(messages=messages, **kwargs)

    backend_module.MEMORY_BACKEND.add = recording_add

    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "task_id": "task_alpha",
            "title": "Alpha task",
            "summary": "完成了第一轮检查",
            "next_action": "下一步是修复召回排序",
        },
    )
    assert response.status_code == 200, response.text
    assert captured
    assert all(isinstance(entry["messages"], list) for entry in captured)
    assert all(entry["messages"][0]["role"] == "user" for entry in captured)


def test_task_summaries_skip_memory_for_system_task(client, auth_headers, backend_module):
    captured: list[dict[str, object]] = []
    original_add = backend_module.MEMORY_BACKEND.add

    def recording_add(*, messages, **kwargs):
        captured.append({"messages": messages, **kwargs})
        return original_add(messages=messages, **kwargs)

    backend_module.MEMORY_BACKEND.add = recording_add

    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "task_id": "task_cron-daily",
            "title": "[cron] daily monitor",
            "summary": "[cron:daily] monitor lowendtalk",
            "next_action": "Current time: 2026-04-07 10:00",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["store_task_memory"] is False
    assert payload["task_kind"] == "system"
    assert captured == []


def test_task_summaries_skip_task_row_when_no_task_memory_fields_are_accepted(client, auth_headers):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "task_id": "task_empty_after_governance",
            "title": "修复共享记忆任务匹配",
            "summary": "NO_REPLY",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["action"] == "skipped"
    assert payload["reason"] == "no_task_memory_fields_accepted"
    assert payload["store_task_memory"] is False

    tasks = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    assert "task_empty_after_governance" not in {task["task_id"] for task in tasks}

    memories = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a", "run_id": "task_empty_after_governance"}).json()["results"]
    assert memories == []


def test_cache_rebuild_restores_index_for_existing_memories(client, auth_headers, backend_module):
    result = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "durable routing note"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    memory_id = result["id"]
    backend_module.delete_cached_memory(memory_id)

    rebuild = client.post("/v1/cache/rebuild", headers=auth_headers, json={"user_id": "user-a"})
    assert rebuild.status_code == 200, rebuild.text
    assert rebuild.json()["rebuilt"] >= 1

    search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "routing", "user_id": "user-a"},
    )
    assert search.status_code == 200, search.text
    assert any(item["id"] == memory_id for item in search.json()["results"])


def test_cache_rebuild_removes_stale_entries(client, auth_headers, backend_module):
    result = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "stale cache entry"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    memory_id = result["id"]
    backend_module.cache_memory_record(
        memory_id=memory_id,
        text="stale cache entry",
        user_id="user-a",
        run_id=None,
        agent_id=None,
        metadata={"domain": "long_term", "category": "project_context"},
    )
    backend_module.MEMORY_BACKEND.delete(memory_id)

    rebuild = client.post("/v1/cache/rebuild", headers=auth_headers, json={"user_id": "user-a"})
    assert rebuild.status_code == 200, rebuild.text

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    assert all(item["id"] != memory_id for item in listed.json()["results"])


def test_v1_healthz_alias_is_available(client, auth_headers):
    response = client.get("/v1/healthz", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True


def test_admin_tasks_can_list_active_tasks_without_user_id(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_a",
        user_id="user-a",
        project_id="project-a",
        title="Task A",
        source_agent="agent-a",
        last_summary="Alpha",
    )
    backend_module.upsert_task(
        task_id="task_b",
        user_id="user-b",
        project_id="project-b",
        title="Task B",
        source_agent="agent-b",
        last_summary="Beta",
    )

    response = client.get("/v1/tasks", headers=auth_headers, params={"status": "active"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [task["task_id"] for task in payload["tasks"]] == ["task_b", "task_a"]


def test_non_admin_tasks_listing_without_user_id_uses_bound_user(client, auth_headers):
    key_response = client.post(
        "/v1/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-alpha",
            "label": "agent alpha",
            "scopes": ["task", "search"],
            "user_id": "user-a",
        },
    )
    assert key_response.status_code == 200, key_response.text
    token = key_response.json()["token"]

    response = client.get("/v1/tasks", headers={"X-API-Key": token}, params={"status": "active"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "tasks": [],
        "page_info": {"limit": 50, "has_more": False, "next_cursor": None},
    }


def test_admin_tasks_listing_defaults_to_recent_50_items(client, auth_headers, backend_module):
    for index in range(60):
        backend_module.upsert_task(
            task_id=f"task_{index:02d}",
            user_id=f"user-{index:02d}",
            project_id="project-alpha",
            title=f"Task {index:02d}",
            source_agent="agent-alpha",
            last_summary=f"Summary {index:02d}",
        )

    response = client.get("/v1/tasks", headers=auth_headers, params={"status": "active"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["tasks"]) == 50
    assert payload["tasks"][0]["task_id"] == "task_59"
    assert payload["tasks"][-1]["task_id"] == "task_10"


def test_task_listing_sanitizes_metadata_titles_using_summary(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_meta",
        user_id="user-a",
        project_id=None,
        title='Conversation info (untrusted metadata): ```json {"message_id":"123"}',
        source_agent="agent-a",
        last_summary="已完成 smoke 测试，下一步是检查前端管理界面。",
    )

    response = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["title"] == "检查前端管理界面"


def test_task_listing_sanitizes_cron_titles(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-29c56761-8d79-44f0-b754-36da75204e6c-mac-op",
        user_id="user-a",
        project_id=None,
        title="[cron:29c56761-8d79-44f0-b754-36da75204e6c Mac OpenCode orphan watchdog (8h)] 你是",
        source_agent="agent-a",
        last_summary="NO_REPLY",
    )

    response = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["title"] == "Mac OpenCode 孤儿进程巡检"
    assert task["task_kind"] == "system"


def test_task_listing_rewrites_keyword_soup_titles(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_todo_followup_deadline",
        user_id="user-a",
        project_id=None,
        title="task todo pending deadline follow-up next action 待办 任务 跟进 截止",
        source_agent="agent-a",
        last_summary="task todo pending deadline follow-up next action 待办 任务 跟进 截止",
    )

    response = client.get("/v1/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["title"] == "待办任务跟进与截止项"


@_requires_frontend_build
def test_ui_index_is_available(client, auth_headers):
    response = client.get("/v1/ui", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "记忆平台管理台" in response.text


@_requires_frontend_build
def test_ui_route_serves_chinese_management_page(client):
    response = client.get("/v1/ui")
    assert response.status_code == 200, response.text
    assert "记忆平台管理台" in response.text


def test_ui_route_reports_missing_build_artifacts(client, auth_headers, backend_module, tmp_path):
    backend_module.FRONTEND_BUILD_DIR = tmp_path / "missing-ui-build"
    response = client.get("/v1/ui", headers=auth_headers)
    assert response.status_code == 503, response.text
    assert "前端构建产物不存在" in response.text


def test_metrics_reflect_route_activity(client, auth_headers):
    route = client.post(
        "/v1/memory-route",
        headers=auth_headers,
        json={
                "user_id": "user-a",
                "agent_id": "agent-a",
                "project_id": "project-alpha",
                "message": "请记住：我偏好简洁 summary。",
                "client_hints": {"explicit_long_term": True},
            },
        )
    assert route.status_code == 200, route.text

    metrics = client.get("/v1/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    payload = metrics.json()["metrics"]
    assert payload["events"]["memory_route"] >= 1
    assert payload["routes"]["long_term"] >= 1


def test_inferred_memory_writes_populate_cache_for_future_governance(client, auth_headers):
    response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "raw input that may be canonicalized"}],
            "user_id": "user-infer",
            "infer": True,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert response.status_code == 200, response.text

    metrics = client.get("/v1/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["metrics"]["memory_cache"]["entries"] == 1


def test_metrics_expose_task_kind_and_memory_domain_breakdown(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-12345-watchdog",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    backend_module.upsert_task(
        task_id="task_work_clean",
        user_id="user-a",
        project_id="automem-demo",
        title="优化前端管理界面",
        source_agent="codex",
        last_summary="完成了首页布局收敛。",
    )
    backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "公司是Example Corp"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    backend_module.cache_memory_record(
        memory_id="mem_long_term_1",
        text="公司是Example Corp",
        user_id="user-a",
        run_id=None,
        agent_id="codex",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "下一步是检查前端管理界面"}],
        user_id="user-a",
        run_id="task_work_clean",
        metadata={"domain": "task", "category": "next_action", "task_id": "task_work_clean"},
    )
    backend_module.cache_memory_record(
        memory_id="mem_task_1",
        text="下一步是检查前端管理界面",
        user_id="user-a",
        run_id="task_work_clean",
        agent_id="codex",
        metadata={"domain": "task", "category": "next_action", "task_id": "task_work_clean"},
    )

    metrics = client.get("/v1/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    payload = metrics.json()["metrics"]
    assert payload["tasks"]["by_kind"]["work"] >= 1
    assert payload["tasks"]["by_kind"]["system"] >= 1
    assert payload["tasks"]["active_work"] >= 1
    assert payload["tasks"]["active_non_work"] >= 1
    assert payload["memory_cache"]["by_domain"]["long_term"] >= 1
    assert payload["memory_cache"]["by_domain"]["task"] >= 1


def test_runtime_topology_exposes_api_worker_and_mcp_contract(client, auth_headers):
    response = client.get("/v1/runtime-topology", headers=auth_headers)
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["runtime"]["api"]["background_submission_endpoint"] == "/v1/governance/jobs"
    assert "/v1/governance/jobs/run-next" in payload["runtime"]["worker"]["run_next_endpoint"]
    assert "memory_route" in payload["runtime"]["mcp_control_plane"]["allowed_hot_path_tools"]


def test_governance_job_queue_executes_consolidation_and_updates_metrics(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-a")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-a")

    enqueued = client.post(
        "/v1/governance/jobs",
        headers=auth_headers,
        json={
            "job_type": "consolidate",
            "payload": {"dry_run": False, "user_id": "user-a"},
            "user_id": "user-a",
            "idempotency_key": "consolidate:user-a:test",
        },
    )
    assert enqueued.status_code == 200, enqueued.text
    queued_payload = enqueued.json()
    assert queued_payload["status"] == "pending"

    processed = client.post(
        "/v1/governance/jobs/run-next",
        headers=auth_headers,
        json={"worker_id": "worker-a"},
    )
    assert processed.status_code == 200, processed.text
    processed_payload = processed.json()
    assert processed_payload["status"] == "processed"
    assert processed_payload["job"]["status"] == "completed"
    assert processed_payload["job"]["result"]["runtime_path"] == "governance_worker"
    assert processed_payload["job"]["result"]["duplicate_long_term_count"] == 1

    fetched = client.get(f"/v1/governance/jobs/{queued_payload['job_id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["status"] == "completed"

    metrics = client.get("/v1/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    job_metrics = metrics.json()["metrics"]["governance_jobs"]
    assert job_metrics["completed"] >= 1
    assert job_metrics["by_type"]["consolidate"] >= 1


def test_governance_job_queue_executes_unscoped_consolidation_from_cached_rows(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="Global Example Corp is durable", user_id="user-a")
    add_long_term_memory(client, auth_headers, text="Global Example Corp is durable", user_id="user-a")

    enqueued = client.post(
        "/v1/governance/jobs",
        headers=auth_headers,
        json={
            "job_type": "consolidate",
            "payload": {"dry_run": True},
            "idempotency_key": "consolidate:global:test",
        },
    )
    assert enqueued.status_code == 200, enqueued.text
    queued_payload = enqueued.json()
    assert queued_payload["status"] == "pending"

    processed = client.post(
        "/v1/governance/jobs/run-next",
        headers=auth_headers,
        json={"worker_id": "worker-global"},
    )
    assert processed.status_code == 200, processed.text
    processed_payload = processed.json()
    assert processed_payload["status"] == "processed"
    assert processed_payload["job"]["status"] == "completed"
    assert processed_payload["job"]["result"]["runtime_path"] == "governance_worker"
    assert processed_payload["job"]["result"]["duplicate_long_term_count"] >= 1


def test_governance_job_enqueue_is_idempotent(client, auth_headers):
    first = client.post(
        "/v1/governance/jobs",
        headers=auth_headers,
        json={
            "job_type": "consolidate",
            "payload": {"dry_run": True},
            "idempotency_key": "same-job",
        },
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/v1/governance/jobs",
        headers=auth_headers,
        json={
            "job_type": "consolidate",
            "payload": {"dry_run": True},
            "idempotency_key": "same-job",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["deduplicated"] is True


def test_infer_true_with_metadata_preserves_backend_infer_flag(client, auth_headers, backend_module):
    observed: list[bool] = []
    original_add = backend_module.MEMORY_BACKEND.add

    def recording_add(messages, **params):
        observed.append(bool(params.get("infer")))
        return original_add(messages, **params)

    backend_module.MEMORY_BACKEND.add = recording_add

    response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "keep infer semantics with metadata"}],
            "user_id": "user-infer",
            "infer": True,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert response.status_code == 200, response.text
    assert observed == [True]


def test_audit_log_endpoint_returns_recent_events(client, auth_headers):
    route = client.post(
        "/v1/memory-route",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-a",
            "message": "请记住：我偏好简洁 summary。",
            "client_hints": {"explicit_long_term": True},
        },
    )
    assert route.status_code == 200, route.text

    audit = client.get("/v1/audit-log?limit=5&event_type=memory_route", headers=auth_headers)
    assert audit.status_code == 200, audit.text
    payload = audit.json()
    assert len(payload["events"]) >= 1
    assert payload["events"][0]["event_type"] == "memory_route"


def test_search_audit_log_records_explainability_summary(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")

    search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "Example", "user_id": "user-a"},
    )
    assert search.status_code == 200, search.text

    audit = client.get("/v1/audit-log?limit=5&event_type=search", headers=auth_headers)
    assert audit.status_code == 200, audit.text
    payload = audit.json()
    assert payload["events"]
    detail = payload["events"][0]["detail"]
    assert "meta" in detail
    assert detail["top_matches"]
    assert "matched_by" in detail["top_matches"][0]
    assert "status" in detail["top_matches"][0]


def test_agent_keys_list_returns_created_key(client, auth_headers):
    created = client.post(
        "/v1/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-list-test",
            "label": "list test",
            "scopes": ["search"],
            "user_id": "user-a",
        },
    )
    assert created.status_code == 200, created.text

    listed = client.get("/v1/agent-keys", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert any(
        item["agent_id"] == "agent-list-test" and item["user_id"] == "user-a"
        for item in listed.json()["keys"]
    )
