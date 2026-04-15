from __future__ import annotations


def create_project_key(
    client,
    auth_headers,
    *,
    scopes,
    user_id: str = "user-a",
    project_ids: list[str] | None = None,
    agent_id: str = "agent-project-test",
):
    response = client.post(
        "/agent-keys",
        headers=auth_headers,
        json={
            "agent_id": agent_id,
            "label": f"{agent_id} key",
            "scopes": scopes,
            "user_id": user_id,
            "project_ids": project_ids or ["project-alpha"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_project_bound_task_flow_defaults_single_project_scope(client, auth_headers):
    token = create_project_key(client, auth_headers, scopes=["task"])

    summary = client.post(
        "/task-summaries",
        headers={"X-API-Key": token},
        json={
            "user_id": "user-a",
            "agent_id": "agent-project-test",
            "task_id": "task_phase04_identity",
            "title": "Implement shared identity scope",
            "summary": "已完成身份模型梳理，下一步是补项目级访问控制测试。",
        },
    )
    assert summary.status_code == 200, summary.text

    tasks = client.get("/tasks", headers={"X-API-Key": token}, params={"status": "active"})
    assert tasks.status_code == 200, tasks.text
    payload = tasks.json()
    assert payload["tasks"][0]["project_id"] == "project-alpha"


def test_project_bound_key_rejects_unauthorized_task_project(client, auth_headers):
    token = create_project_key(client, auth_headers, scopes=["task"], project_ids=["project-alpha"])

    response = client.post(
        "/task-summaries",
        headers={"X-API-Key": token},
        json={
            "user_id": "user-a",
            "agent_id": "agent-project-test",
            "project_id": "project-beta",
            "task_id": "task_forbidden_project",
            "title": "Forbidden scope",
            "summary": "继续推进 project beta。",
        },
    )
    assert response.status_code == 403


def test_multi_project_key_requires_explicit_project_for_task_flow(client, auth_headers):
    token = create_project_key(
        client,
        auth_headers,
        scopes=["task"],
        project_ids=["project-alpha", "project-beta"],
        agent_id="agent-multi-project",
    )

    response = client.post(
        "/task-summaries",
        headers={"X-API-Key": token},
        json={
            "user_id": "user-a",
            "agent_id": "agent-multi-project",
            "task_id": "task_missing_project_scope",
            "title": "Need explicit project",
            "summary": "继续推进共享权限模型。",
        },
    )
    assert response.status_code == 400


def test_project_bound_memory_search_only_returns_allowed_project(client, auth_headers):
    admin_project_alpha = client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Identity roadmap for alpha"}],
            "user_id": "user-a",
            "project_id": "project-alpha",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert admin_project_alpha.status_code == 200, admin_project_alpha.text

    admin_project_beta = client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Identity roadmap for beta"}],
            "user_id": "user-a",
            "project_id": "project-beta",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert admin_project_beta.status_code == 200, admin_project_beta.text

    token = create_project_key(client, auth_headers, scopes=["store", "search"], project_ids=["project-alpha"])

    scoped_write = client.post(
        "/memories",
        headers={"X-API-Key": token},
        json={
            "messages": [{"role": "user", "content": "Alpha scoped memory write"}],
            "user_id": "user-a",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert scoped_write.status_code == 200, scoped_write.text

    search = client.post("/search", headers={"X-API-Key": token}, json={"query": "Identity roadmap", "limit": 10})
    assert search.status_code == 200, search.text
    memories = [item["memory"] for item in search.json()["results"]]
    assert "Identity roadmap for alpha" in memories
    assert "Identity roadmap for beta" not in memories


def test_project_bound_search_rejects_conflicting_project_filter(client, auth_headers):
    token = create_project_key(client, auth_headers, scopes=["search"], project_ids=["project-alpha"])

    response = client.post(
        "/search",
        headers={"X-API-Key": token},
        json={
            "query": "identity",
            "project_id": "project-alpha",
            "filters": {"project_id": "project-beta"},
        },
    )
    assert response.status_code == 400


def test_project_bound_key_cannot_fetch_task_from_other_project(client, auth_headers):
    alpha_token = create_project_key(client, auth_headers, scopes=["task"], project_ids=["project-alpha"], agent_id="agent-alpha")

    created = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "admin-agent",
            "project_id": "project-beta",
            "task_id": "task_beta_secret",
            "title": "Beta only task",
            "summary": "继续推进 beta 侧改动。",
        },
    )
    assert created.status_code == 200, created.text

    fetched = client.get("/tasks/task_beta_secret", headers={"X-API-Key": alpha_token})
    assert fetched.status_code == 404


def test_project_bound_key_cannot_close_task_from_other_project(client, auth_headers):
    alpha_token = create_project_key(client, auth_headers, scopes=["task"], project_ids=["project-alpha"], agent_id="agent-alpha-close")

    created = client.post(
        "/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": "admin-agent",
            "project_id": "project-beta",
            "task_id": "task_beta_close_blocked",
            "title": "Beta close blocked",
            "summary": "继续推进 beta 侧关闭测试。",
        },
    )
    assert created.status_code == 200, created.text

    closed = client.post(
        "/tasks/task_beta_close_blocked/close",
        headers={"X-API-Key": alpha_token},
        json={"reason": "should fail"},
    )
    assert closed.status_code == 404


def test_project_bound_key_cannot_fetch_memory_from_other_project(client, auth_headers):
    beta_memory = client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Beta confidential memory"}],
            "user_id": "user-a",
            "project_id": "project-beta",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert beta_memory.status_code == 200, beta_memory.text
    memory_id = beta_memory.json()["results"][0]["id"]

    alpha_token = create_project_key(client, auth_headers, scopes=["search"], project_ids=["project-alpha"], agent_id="agent-alpha-memory")
    fetched = client.get(f"/memories/{memory_id}", headers={"X-API-Key": alpha_token})
    assert fetched.status_code == 404


def test_project_bound_key_cannot_delete_memory_from_other_project(client, auth_headers):
    beta_memory = client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Beta delete protected memory"}],
            "user_id": "user-a",
            "project_id": "project-beta",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    assert beta_memory.status_code == 200, beta_memory.text
    memory_id = beta_memory.json()["results"][0]["id"]

    alpha_token = create_project_key(
        client,
        auth_headers,
        scopes=["forget"],
        project_ids=["project-alpha"],
        agent_id="agent-alpha-delete",
    )
    deleted = client.delete(f"/memories/{memory_id}", headers={"X-API-Key": alpha_token})
    assert deleted.status_code == 404

    still_there = client.get(f"/memories/{memory_id}", headers=auth_headers)
    assert still_there.status_code == 200, still_there.text


def test_project_bound_get_memories_defaults_to_single_project_scope(client, auth_headers):
    client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Alpha listing memory"}],
            "user_id": "user-a",
            "project_id": "project-alpha",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )
    client.post(
        "/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Beta listing memory"}],
            "user_id": "user-a",
            "project_id": "project-beta",
            "infer": False,
            "metadata": {"domain": "long_term", "category": "project_context"},
        },
    )

    alpha_token = create_project_key(client, auth_headers, scopes=["search"], project_ids=["project-alpha"], agent_id="agent-alpha-list")
    listed = client.get("/memories", headers={"X-API-Key": alpha_token}, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    memories = [item["memory"] for item in listed.json()["results"]]
    assert "Alpha listing memory" in memories
    assert "Beta listing memory" not in memories
