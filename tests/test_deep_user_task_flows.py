from __future__ import annotations


def _task_ids(client, auth_headers, *, user_id: str, status: str) -> set[str]:
    response = client.get(
        "/v1/tasks",
        headers=auth_headers,
        params={"user_id": user_id, "status": status, "limit": 200},
    )
    assert response.status_code == 200, response.text
    return {task["task_id"] for task in response.json()["tasks"]}


def _task_memories(client, auth_headers, *, user_id: str, task_id: str) -> list[dict[str, object]]:
    response = client.get(
        "/v1/memories",
        headers=auth_headers,
        params={"user_id": user_id, "run_id": task_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["results"]


def test_multi_hop_handoff_keeps_task_identity_progress_and_next_action(client, auth_headers):
    first = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-alpha",
            "project_id": "automem-demo",
            "task_id": "task_frontend-panel",
            "title": "前端管理界面优化",
            "summary": "完成了首页布局收敛。",
            "progress": "首页布局已经收敛，导航层级也完成了第一轮整理。",
            "next_action": "下一步是检查前端管理界面的搜索结果排序。",
            "message": "继续处理前端管理界面优化任务",
        },
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["action"] == "stored"
    assert first_payload["task"]["task_id"] == "task_frontend-panel"
    assert first_payload["store_task_memory"] is True

    resolved = client.post(
        "/v1/task-resolution",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-beta",
            "project_id": "automem-demo",
            "message": "前端管理界面的下一步是什么",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["action"] == "match_existing_task"
    assert resolved.json()["task_id"] == "task_frontend-panel"

    second = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "agent-beta",
            "project_id": "automem-demo",
            "task_id": "task_frontend-panel",
            "title": "前端管理界面优化",
            "summary": "搜索结果排序修完了，开始整理筛选交互。",
            "progress": "搜索结果排序已经调整完成，筛选交互进入联调。",
            "next_action": "前端管理界面的下一步是验证筛选交互和空状态文案。",
            "message": "继续推进前端管理界面优化任务",
        },
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["action"] == "stored"
    assert second_payload["task"]["task_id"] == "task_frontend-panel"

    task = client.get("/v1/tasks/task_frontend-panel", headers=auth_headers)
    assert task.status_code == 200, task.text
    task_payload = task.json()
    assert task_payload["task_id"] == "task_frontend-panel"
    assert task_payload["status"] == "active"
    assert task_payload["last_summary"] == "搜索结果排序修完了，开始整理筛选交互。"

    search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={
            "query": "前端管理界面的下一步是什么",
            "user_id": "user-a",
            "project_id": "automem-demo",
            "limit": 5,
        },
    )
    assert search.status_code == 200, search.text
    search_payload = search.json()
    assert search_payload["meta"]["intent"] == "task_lookup"
    assert search_payload["results"], search_payload
    top = search_payload["results"][0]
    assert top["memory"] == "前端管理界面的下一步是验证筛选交互和空状态文案。"
    assert top["metadata"]["task_id"] == "task_frontend-panel"
    assert top["metadata"]["category"] == "next_action"
    assert top["status"] == "active"

    memories = _task_memories(client, auth_headers, user_id="user-a", task_id="task_frontend-panel")
    categories = {item["metadata"]["category"] for item in memories}
    assert {"handoff", "progress", "next_action"} <= categories
    assert sum(1 for item in memories if item["metadata"]["category"] == "next_action") >= 2


def test_layered_cleanup_archives_noise_and_prunes_old_non_work_without_hiding_real_work(
    client,
    auth_headers,
    backend_module,
):
    real_work = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "codex",
            "project_id": "automem-demo",
            "task_id": "task_real_work",
            "title": "优化共享记忆管理界面",
            "summary": "完成了第一轮信息架构收敛。",
            "next_action": "下一步是验证筛选和排序交互。",
        },
    )
    assert real_work.status_code == 200, real_work.text

    backend_module.upsert_task(
        task_id="task_cron-active-noise",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    backend_module.upsert_task(
        task_id="task_cron-archived-noise",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    archived = client.post("/v1/tasks/task_cron-archived-noise/archive", headers=auth_headers, json={"reason": "cleanup"})
    assert archived.status_code == 200, archived.text

    task_memory = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "NO_REPLY"}],
        user_id="user-a",
        run_id="task_cron-archived-noise",
        metadata={"domain": "task", "category": "handoff", "task_id": "task_cron-archived-noise"},
    )
    backend_module.cache_memory_record(
        memory_id=task_memory["id"],
        text="NO_REPLY",
        user_id="user-a",
        run_id="task_cron-archived-noise",
        agent_id="openclaw-ring",
        metadata={"domain": "task", "category": "handoff", "task_id": "task_cron-archived-noise"},
    )

    normalized = client.post(
        "/v1/tasks/normalize",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "archive_non_work_active": True,
            "prune_non_work_archived": True,
            "dry_run": False,
        },
    )
    assert normalized.status_code == 200, normalized.text
    payload = normalized.json()
    assert payload["archived_tasks"] >= 1
    assert payload["deleted_archived_non_work_tasks"] >= 1
    assert payload["deleted_archived_non_work_memory"] >= 1

    active_ids = _task_ids(client, auth_headers, user_id="user-a", status="active")
    archived_ids = _task_ids(client, auth_headers, user_id="user-a", status="archived")
    assert "task_real_work" in active_ids
    assert "task_cron-active-noise" not in active_ids
    assert "task_cron-active-noise" in archived_ids
    assert "task_cron-archived-noise" not in archived_ids

    pruned_memories = _task_memories(client, auth_headers, user_id="user-a", task_id="task_cron-archived-noise")
    assert pruned_memories == []
