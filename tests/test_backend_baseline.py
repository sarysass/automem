from __future__ import annotations


def add_long_term_memory(client, auth_headers, *, text: str, user_id: str, category: str = "project_context"):
    response = client.post(
        "/memories",
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
    response = client.post("/tasks/task_missing/close", headers=auth_headers, json={"reason": "cleanup"})
    assert response.status_code == 404


def test_archive_task_returns_404_for_unknown_task(client, auth_headers):
    response = client.post("/tasks/task_missing/archive", headers=auth_headers, json={"reason": "cleanup"})
    assert response.status_code == 404


def test_consolidate_respects_requested_user_scope(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-a")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-a")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-b")
    add_long_term_memory(client, auth_headers, text="Example Corp is durable", user_id="user-b")

    response = client.post(
        "/consolidate",
        headers=auth_headers,
        json={"dry_run": True, "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["duplicate_long_term_count"] == 1
    assert payload["user_id"] == "user-a"


def test_add_memory_canonicalizes_preference_alias_and_skips_duplicate(client, auth_headers):
    english = client.post(
        "/memories",
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
        "/memories",
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

    listed = client.get("/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    results = listed.json()["results"]
    assert [item["memory"] for item in results] == ["偏好使用中文沟通"]


def test_add_memory_rejects_task_noise_markers(client, auth_headers):
    for text in ("NO_REPLY", "[[reply_to_current]] 已完成实际测试"):
        response = client.post(
            "/memories",
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

    listed = client.get("/memories", headers=auth_headers, params={"user_id": "user-a", "run_id": "task_alpha"})
    assert listed.status_code == 200, listed.text
    assert listed.json()["results"] == []


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
        "/consolidate",
        headers=auth_headers,
        json={"dry_run": False, "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["canonicalized_long_term_count"] == 1
    assert payload["deleted_noise_count"] == 1

    listed = client.get("/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    memories = listed.json()["results"]
    assert [item["memory"] for item in memories if item["metadata"].get("category") == "preference"] == ["偏好使用中文沟通"]
    assert all(item["memory"] != "NO_REPLY" for item in memories)


def test_search_uses_cache_path_without_get_all(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="alpha routing policy", user_id="user-a")

    def fail_get_all(**_kwargs):
        raise AssertionError("get_all should not be used by hybrid search")

    backend_module.MEMORY_BACKEND.get_all = fail_get_all

    response = client.post(
        "/search",
        headers=auth_headers,
        json={"query": "routing", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["mode"] == "hybrid"
    assert len(payload["results"]) >= 1


def test_admin_search_without_identity_scope_falls_back_to_cache_only(client, auth_headers):
    response = client.post(
        "/search",
        headers=auth_headers,
        json={"query": "示例用户"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["mode"] == "cache_only"


def test_identity_query_prefers_user_profile_over_task_noise(client, auth_headers, backend_module):
    add_long_term_memory(client, auth_headers, text="姓名是示例用户", user_id="user-a", category="user_profile")
    task_response = client.post(
        "/memories",
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
        "/search",
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
        "/search",
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
        "/memories",
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
        "/search",
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
        "/search",
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
        "/search",
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
        "/search",
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
        "/search",
        headers=auth_headers,
        json={"query": "我的名字叫什么", "user_id": "user-a", "limit": 25},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["limit"] == 25
    assert len(payload["results"]) <= 25
    assert payload["results"][0]["memory"] == "姓名是示例用户"


def test_admin_search_without_user_scope_can_query_global_cache(client, auth_headers):
    add_long_term_memory(client, auth_headers, text="公司是Example Corp", user_id="user-a", category="project_context")

    response = client.post(
        "/search",
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
        "/search",
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
        "/memories",
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
        "/search",
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
        "/memories",
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
        "/memories",
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
        "/search",
        headers=auth_headers,
        json={"query": "视频压缩方案的下一步是什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "task_lookup"
    assert "视频压缩" in payload["results"][0]["memory"]


def test_task_query_with_subject_returns_empty_when_no_matching_task_memory(client, auth_headers):
    generic = client.post(
        "/memories",
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
        "/search",
        headers=auth_headers,
        json={"query": "视频压缩方案的下一步是什么", "user_id": "user-a"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["intent"] == "task_lookup"
    assert payload["results"] == []


def test_task_resolution_handles_next_step_question_against_existing_task(client, auth_headers):
    summary_response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "memory-hub",
            "task_id": "task_frontend-panel",
            "title": "前端管理界面优化",
            "summary": "完成了首页布局收敛。",
            "next_action": "下一步是检查前端管理界面的搜索结果排序。",
            "message": "继续处理前端管理界面优化任务",
        },
    )
    assert summary_response.status_code == 200, summary_response.text

    resolution = client.post(
        "/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "memory-hub",
            "message": "前端管理界面的下一步是什么",
        },
    )
    assert resolution.status_code == 200, resolution.text
    payload = resolution.json()
    assert payload["action"] == "match_existing_task"
    assert payload["task_id"] == "task_frontend-panel"


def test_task_resolution_does_not_create_task_for_status_check_question(client, auth_headers):
    resolution = client.post(
        "/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "memory-hub",
            "message": "当前执行任务状态是什么",
        },
    )
    assert resolution.status_code == 200, resolution.text
    payload = resolution.json()
    assert payload["action"] == "no_task"


def test_task_resolution_avoids_false_positive_match_for_unrelated_next_step_question(client, auth_headers):
    response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "memory-hub",
            "task_id": "task_shared_memory",
            "title": "继续共享记忆系统的任务并先结合已有约束",
            "summary": "完成了回滚与 smoke 测试。",
            "next_action": "下一步是继续调优共享记忆系统的 recall 效果。",
        },
    )
    assert response.status_code == 200, response.text

    resolution = client.post(
        "/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "memory-hub",
            "message": "视频压缩方案的下一步是什么",
        },
    )
    assert resolution.status_code == 200, resolution.text
    payload = resolution.json()
    assert payload["action"] == "no_task"


def test_tasks_list_marks_system_and_meta_tasks(client, auth_headers):
    cron_task = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "openclaw-ring",
            "task_id": "task_cron-12345-watchdog",
            "title": "[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
            "summary": "NO_REPLY",
        },
    )
    assert cron_task.status_code == 200, cron_task.text

    meta_task = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "openclaw-wing",
            "task_id": "task_conversation-info-untrusted-metadata",
            "title": "Conversation info (untrusted metadata): ...",
            "summary": "[[reply_to_current]] 目前我这次查到的共享 memory里，没有成型的 task / todo 清单。",
        },
    )
    assert meta_task.status_code == 200, meta_task.text

    work_task = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "memory-hub",
            "task_id": "task_automem-ui",
            "title": "优化前端管理界面",
            "summary": "完成了首页布局收敛。",
        },
    )
    assert work_task.status_code == 200, work_task.text

    response = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
    assert response.status_code == 200, response.text
    tasks = {task["task_id"]: task for task in response.json()["tasks"]}
    assert tasks["task_cron-12345-watchdog"]["task_kind"] == "system"
    assert tasks["task_conversation-info-untrusted-metadata"]["task_kind"] == "meta"
    assert tasks["task_automem-ui"]["task_kind"] == "work"


def test_question_style_task_title_is_classified_as_meta(client, auth_headers):
    response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "memory-hub",
            "task_id": "task_共享记忆系统这个任务的下一步是什么",
            "title": "共享记忆系统这个任务的下一步是什么",
            "summary": "共享记忆系统这个任务的下一步是什么",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    assert indexed["task_共享记忆系统这个任务的下一步是什么"]["task_kind"] == "meta"


def test_task_status_question_title_is_classified_as_meta(client, auth_headers):
    response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "memory-hub",
            "task_id": "task_当前执行任务状态是什么",
            "title": "当前执行任务状态是什么",
            "summary": "当前执行任务状态是什么",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    assert indexed["task_当前执行任务状态是什么"]["task_kind"] == "meta"


def test_tasks_list_exposes_clean_display_fields(client, auth_headers):
    response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "memory-hub",
            "task_id": "task_updated-automem-frontend-typography",
            "title": "Updated automem frontend typography to use Songti SC across the full UI,",
            "summary": "[[reply_to_current]] 已完成 smoke 测试，下一步是检查前端管理界面。",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    task = indexed["task_updated-automem-frontend-typography"]
    assert task["display_title"] == "前端字体与溢出修复验证"
    assert task["summary_preview"] == "检查前端管理界面"


def test_tasks_list_maps_no_reply_summary_to_empty_preview(client, auth_headers):
    response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "openclaw-ring",
            "task_id": "task_cron-12345-watchdog",
            "title": "[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
            "summary": "NO_REPLY",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    task = indexed["task_cron-12345-watchdog"]
    assert task["display_title"] == "Mac OpenCode 孤儿进程巡检"
    assert task["summary_preview"] is None


def test_tasks_list_rewrites_task_resolution_titles_and_keyword_soup_preview(client, auth_headers):
    response = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "memory-hub",
            "task_id": "task_task-resolution-centralization",
            "title": "继续完成共享记忆系统的中心化 task resolution 改造并做全端部署验证",
            "summary": "task todo pending deadline follow-up next action 待办 任务 跟进 截止",
        },
    )
    assert response.status_code == 200, response.text

    tasks = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    indexed = {task["task_id"]: task for task in tasks}
    task = indexed["task_task-resolution-centralization"]
    assert task["display_title"] == "共享记忆系统 task resolution 中心化与全端验证"
    assert task["summary_preview"] == "梳理待办、跟进与截止项"


def test_task_normalize_archives_non_work_items_and_rewrites_titles(client, auth_headers):
    client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "openclaw-ring",
            "task_id": "task_cron-12345-watchdog",
            "title": "[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
            "summary": "NO_REPLY",
        },
    )
    client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "task_id": "task_当前执行任务状态是什么",
            "title": "当前执行任务状态是什么",
            "summary": "当前执行任务状态是什么",
        },
    )
    client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "memory-hub",
            "task_id": "task_work_clean",
            "title": "优化前端管理界面",
            "summary": "完成了首页布局收敛。",
        },
    )

    response = client.post(
        "/tasks/normalize",
        headers=auth_headers,
        json={"user_id": "user-a", "archive_non_work_active": True, "dry_run": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["archived_tasks"] >= 2

    active = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"}).json()["tasks"]
    active_ids = {task["task_id"] for task in active}
    assert "task_work_clean" in active_ids
    assert "task_cron-12345-watchdog" not in active_ids
    assert "task_当前执行任务状态是什么" not in active_ids

    archived = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "archived"}).json()["tasks"]
    archived_index = {task["task_id"]: task for task in archived}
    assert archived_index["task_cron-12345-watchdog"]["title"] == "Mac OpenCode 孤儿进程巡检"


def test_agent_key_enforces_bound_agent_identity(client, auth_headers):
    key_response = client.post(
        "/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-alpha",
            "label": "agent alpha",
            "scopes": ["store", "search", "route", "task", "metrics"],
        },
    )
    assert key_response.status_code == 200, key_response.text
    token = key_response.json()["token"]

    mismatch = client.post(
        "/memories",
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
        "/memories",
        headers={"X-API-Key": token},
        json={
            "messages": [{"role": "user", "content": "alpha"}],
            "metadata": {"domain": "long_term", "category": "project_context"},
            "infer": False,
        },
    )
    assert ok.status_code == 200, ok.text


def test_agent_key_search_is_bound_to_default_user(client, auth_headers):
    key_response = client.post(
        "/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-alpha",
            "label": "agent alpha",
            "scopes": ["search"],
        },
    )
    assert key_response.status_code == 200, key_response.text
    token = key_response.json()["token"]

    mismatch = client.post(
        "/search",
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
        "/task-summaries",
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


def test_cache_rebuild_restores_index_for_existing_memories(client, auth_headers, backend_module):
    result = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "durable routing note"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    memory_id = result["id"]
    backend_module.delete_cached_memory(memory_id)

    rebuild = client.post("/cache/rebuild", headers=auth_headers, json={"user_id": "user-a"})
    assert rebuild.status_code == 200, rebuild.text
    assert rebuild.json()["rebuilt"] >= 1

    search = client.post(
        "/search",
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

    rebuild = client.post("/cache/rebuild", headers=auth_headers, json={"user_id": "user-a"})
    assert rebuild.status_code == 200, rebuild.text

    listed = client.get("/memories", headers=auth_headers, params={"user_id": "user-a"})
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

    response = client.get("/tasks", headers=auth_headers, params={"status": "active"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [task["task_id"] for task in payload["tasks"]] == ["task_b", "task_a"]


def test_non_admin_tasks_listing_without_user_id_uses_bound_default_user(client, auth_headers):
    key_response = client.post(
        "/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-alpha",
            "label": "agent alpha",
            "scopes": ["task", "search"],
        },
    )
    assert key_response.status_code == 200, key_response.text
    token = key_response.json()["token"]

    response = client.get("/tasks", headers={"X-API-Key": token}, params={"status": "active"})
    assert response.status_code == 200, response.text
    assert response.json() == {"tasks": []}


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

    response = client.get("/tasks", headers=auth_headers, params={"status": "active"})
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

    response = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
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

    response = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
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

    response = client.get("/tasks", headers=auth_headers, params={"user_id": "user-a", "status": "active"})
    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["title"] == "待办任务跟进与截止项"


def test_ui_index_is_available(client, auth_headers):
    response = client.get("/ui", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "记忆平台管理台" in response.text


def test_ui_route_serves_chinese_management_page(client):
    response = client.get("/ui")
    assert response.status_code == 200, response.text
    assert "记忆平台管理台" in response.text


def test_ui_route_reports_missing_build_artifacts(client, auth_headers, backend_module, tmp_path):
    backend_module.FRONTEND_BUILD_DIR = tmp_path / "missing-ui-build"
    response = client.get("/ui", headers=auth_headers)
    assert response.status_code == 503, response.text
    assert "前端构建产物不存在" in response.text


def test_metrics_reflect_route_activity(client, auth_headers):
    route = client.post(
        "/memory-route",
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

    metrics = client.get("/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    payload = metrics.json()["metrics"]
    assert payload["events"]["memory_route"] >= 1
    assert payload["routes"]["long_term"] >= 1


def test_inferred_memory_writes_do_not_populate_cache_directly(client, auth_headers):
    response = client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "raw input that may be canonicalized"}],
            "user_id": "user-infer",
            "infer": True,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert response.status_code == 200, response.text

    metrics = client.get("/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["metrics"]["memory_cache"]["entries"] == 0


def test_audit_log_endpoint_returns_recent_events(client, auth_headers):
    route = client.post(
        "/memory-route",
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


def test_agent_keys_list_returns_created_key(client, auth_headers):
    created = client.post(
        "/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": "agent-list-test",
            "label": "list test",
            "scopes": ["search"],
        },
    )
    assert created.status_code == 200, created.text

    listed = client.get("/agent-keys", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert any(item["agent_id"] == "agent-list-test" for item in listed.json()["keys"])
