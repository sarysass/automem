from __future__ import annotations


def add_long_term_memory(
    client,
    auth_headers,
    *,
    text: str,
    user_id: str,
    category: str = "project_context",
    project_id: str | None = None,
):
    response = client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": text}],
            "user_id": user_id,
            "project_id": project_id,
            "infer": False,
            "metadata": {"domain": "long_term", "category": category},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_intent_style_language_query_recalls_current_preference_in_top_three(client, auth_headers):
    original = add_long_term_memory(
        client,
        auth_headers,
        text="偏好使用中文沟通",
        user_id="user-a",
        category="preference",
    )

    updated = add_long_term_memory(
        client,
        auth_headers,
        text="偏好使用英文沟通",
        user_id="user-a",
        category="preference",
    )
    updated_memory_id = updated["results"][0]["id"]
    superseded_memory_id = original["results"][0]["id"]

    response = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "我应该用什么语言回复你", "user_id": "user-a", "limit": 3},
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["meta"]["intent"] == "preference_lookup"
    assert payload["meta"]["effective_domain"] == "long_term"
    assert payload["meta"]["history_mode"] is False
    assert payload["results"], payload

    memories = [item["memory"] for item in payload["results"]]
    assert "偏好使用英文沟通" in memories
    assert memories.index("偏好使用英文沟通") < 3
    assert "偏好使用中文沟通" not in memories

    winner = next(item for item in payload["results"] if item["memory"] == "偏好使用英文沟通")
    assert winner["status"] == "active"
    assert winner["source_memory_id"] == updated_memory_id
    assert "text" in winner["matched_fields"]
    assert winner["explainability"]["status"] == "active"
    assert winner["explainability"]["source_memory_id"] == updated_memory_id
    assert winner["explainability"]["supersedes"] == [superseded_memory_id]
    assert any(term in {"什么语言", "语言", "沟通"} for term in winner["explainability"]["matched_terms"])


def test_supersede_story_keeps_current_first_and_exposes_history_trace(client, auth_headers):
    first = add_long_term_memory(
        client,
        auth_headers,
        text="偏好使用中文沟通",
        user_id="user-a",
        category="preference",
    )
    second = add_long_term_memory(
        client,
        auth_headers,
        text="偏好使用英文沟通",
        user_id="user-a",
        category="preference",
    )

    first_id = first["results"][0]["id"]
    second_id = second["results"][0]["id"]

    listed = client.get("/v1/memories", headers=auth_headers, params={"user_id": "user-a"})
    assert listed.status_code == 200, listed.text
    by_status = {item["metadata"]["status"]: item for item in listed.json()["results"]}
    assert by_status["active"]["memory"] == "偏好使用英文沟通"
    assert by_status["active"]["metadata"]["supersedes"] == [first_id]
    assert by_status["superseded"]["memory"] == "偏好使用中文沟通"
    assert by_status["superseded"]["metadata"]["superseded_by"] == second_id

    current = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "沟通", "user_id": "user-a", "limit": 5},
    )
    assert current.status_code == 200, current.text
    current_payload = current.json()
    assert [item["status"] for item in current_payload["results"]] == ["active"]
    assert [item["memory"] for item in current_payload["results"]] == ["偏好使用英文沟通"]
    assert current_payload["results"][0]["explainability"]["supersedes"] == [first_id]

    history = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "沟通", "user_id": "user-a", "include_history": True, "limit": 5},
    )
    assert history.status_code == 200, history.text
    history_payload = history.json()
    assert [item["memory"] for item in history_payload["results"]] == ["偏好使用英文沟通", "偏好使用中文沟通"]
    assert [item["status"] for item in history_payload["results"]] == ["active", "superseded"]
    assert history_payload["results"][1]["explainability"]["superseded_by"] == second_id


def test_conflict_review_story_preserves_active_fact_until_history_is_requested(client, auth_headers):
    active = add_long_term_memory(
        client,
        auth_headers,
        text="公司是Example Corp",
        user_id="user-a",
        category="project_context",
    )

    conflict = add_long_term_memory(
        client,
        auth_headers,
        text="公司是Another Corp",
        user_id="user-a",
        category="project_context",
    )

    active_id = active["results"][0]["id"]
    conflict_id = conflict["results"][0]["id"]

    assert conflict["fact_status"] == "conflict_review"
    assert conflict["fact_action"] == "review_required"
    assert conflict["conflicts_with"] == [active_id]

    default_search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={"query": "公司", "user_id": "user-a", "limit": 5},
    )
    assert default_search.status_code == 200, default_search.text
    default_payload = default_search.json()
    assert [item["memory"] for item in default_payload["results"]] == ["公司是Example Corp"]
    assert [item["status"] for item in default_payload["results"]] == ["active"]

    review_search = client.post(
        "/v1/search",
        headers=auth_headers,
        json={
            "query": "Another",
            "user_id": "user-a",
            "include_history": True,
            "filters": {"status": "conflict_review"},
            "limit": 5,
        },
    )
    assert review_search.status_code == 200, review_search.text
    review_payload = review_search.json()
    assert [item["memory"] for item in review_payload["results"]] == ["公司是Another Corp"]
    review = review_payload["results"][0]
    assert review["status"] == "conflict_review"
    assert review["source_memory_id"] == conflict_id
    assert review["explainability"]["status"] == "conflict_review"
    assert review["explainability"]["conflict_status"] == "needs_review"
    assert review["explainability"]["review_status"] == "pending"
