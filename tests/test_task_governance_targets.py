from __future__ import annotations

import pytest

from backend.governance.task_policy import classify_task_kind, should_materialize_task


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


@pytest.mark.parametrize(
    ("task_id", "agent_id", "title", "summary"),
    [
        (
            "task_cron-daily-monitor",
            "openclaw-ring",
            "[cron:daily Mac OpenCode orphan watchdog (8h)] NO_REPLY",
            "NO_REPLY",
        ),
        (
            "task_question-next-step",
            "codex",
            "共享记忆系统这个任务的下一步是什么",
            "共享记忆系统这个任务的下一步是什么",
        ),
        (
            "task_media-attached-demo",
            "openclaw-wing",
            "[media attached: /root/.openclaw/media/inbound/demo.png]",
            "[media attached: /root/.openclaw/media/inbound/demo.png]",
        ),
        (
            "task_system-reminder-demo",
            "opencode-mac",
            "<system-reminder> [BACKGROUND TASK COMPLETED] ID: bg_123",
            "<system-reminder> [BACKGROUND TASK COMPLETED] ID: bg_123",
        ),
    ],
)
def test_non_work_task_summaries_do_not_materialize_tasks_or_task_memory(
    client,
    auth_headers,
    task_id: str,
    agent_id: str,
    title: str,
    summary: str,
):
    response = client.post(
        "/v1/task-summaries",
        headers=auth_headers,
        json={
            "user_id": "user-a",
            "agent_id": agent_id,
            "task_id": task_id,
            "title": title,
            "summary": summary,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["store_task_memory"] is False

    assert task_id not in _task_ids(client, auth_headers, user_id="user-a", status="active")
    assert task_id not in _task_ids(client, auth_headers, user_id="user-a", status="archived")
    assert _task_memories(client, auth_headers, user_id="user-a", task_id=task_id) == []


def test_consolidate_reports_task_deltas_for_historical_garbage_only_once(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_cron-12345-watchdog",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )
    work = client.post(
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
    assert work.status_code == 200, work.text

    first = client.post(
        "/v1/consolidate",
        headers=auth_headers,
        json={"dry_run": False, "user_id": "user-a"},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["normalized_tasks_count"] > 0
    assert first_payload["task_reclassified_count"] > 0
    assert first_payload["active_non_work_detected_count"] > 0

    second = client.post(
        "/v1/consolidate",
        headers=auth_headers,
        json={"dry_run": False, "user_id": "user-a"},
    )
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert second_payload["normalized_tasks_count"] == 0
    assert second_payload["task_reclassified_count"] == 0
    assert second_payload["active_non_work_detected_count"] == 0
    assert second_payload["archived_non_work_detected_count"] > 0


def test_metrics_expose_task_kind_and_memory_domain_breakdown(client, auth_headers, backend_module):
    backend_module.upsert_task(
        task_id="task_work_clean",
        user_id="user-a",
        project_id="automem-demo",
        title="优化前端管理界面",
        source_agent="codex",
        last_summary="完成了首页布局收敛。",
    )
    backend_module.upsert_task(
        task_id="task_cron-12345-watchdog",
        user_id="user-a",
        project_id=None,
        title="[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
        source_agent="openclaw-ring",
        last_summary="NO_REPLY",
    )

    long_term = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "公司是Example Corp"}],
        user_id="user-a",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    backend_module.cache_memory_record(
        memory_id=long_term["id"],
        text="公司是Example Corp",
        user_id="user-a",
        run_id=None,
        agent_id="codex",
        metadata={"domain": "long_term", "category": "project_context"},
    )

    task_memory = backend_module.MEMORY_BACKEND.add(
        [{"role": "user", "content": "下一步是检查前端管理界面"}],
        user_id="user-a",
        run_id="task_work_clean",
        agent_id="codex",
        metadata={"domain": "task", "category": "next_action", "task_id": "task_work_clean"},
    )
    backend_module.cache_memory_record(
        memory_id=task_memory["id"],
        text="下一步是检查前端管理界面",
        user_id="user-a",
        run_id="task_work_clean",
        agent_id="codex",
        metadata={"domain": "task", "category": "next_action", "task_id": "task_work_clean"},
    )

    response = client.get("/v1/metrics", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()["metrics"]

    assert payload["tasks"]["by_kind"]["work"] >= 1
    assert payload["tasks"]["by_kind"]["system"] >= 1
    assert payload["memory_cache"]["by_domain"]["long_term"] >= 1
    assert payload["memory_cache"]["by_domain"]["task"] >= 1


@pytest.mark.parametrize(
    ("task_id", "title", "last_summary", "source_agent", "project_id", "expected_kind"),
    [
        (
            "task_cron-12345-watchdog",
            "[cron:12345 Mac OpenCode orphan watchdog (8h)] NO_REPLY",
            "NO_REPLY",
            "openclaw-ring",
            None,
            "system",
        ),
        (
            "task_question-next-step",
            "共享记忆系统这个任务的下一步是什么",
            "共享记忆系统这个任务的下一步是什么",
            "codex",
            None,
            "meta",
        ),
        (
            "task_daily_snapshot",
            "daily monitoring task snapshot",
            "updated dashboard snapshot",
            "codex",
            None,
            "snapshot",
        ),
        (
            "task_real_work",
            "优化共享记忆管理界面",
            "完成了第一轮信息架构收敛。",
            "codex",
            "automem-demo",
            "work",
        ),
    ],
)
def test_classify_task_kind_covers_system_meta_snapshot_and_work(
    task_id: str,
    title: str,
    last_summary: str,
    source_agent: str,
    project_id: str | None,
    expected_kind: str,
):
    assert (
        classify_task_kind(
            task_id=task_id,
            title=title,
            last_summary=last_summary,
            source_agent=source_agent,
            project_id=project_id,
        )
        == expected_kind
    )


@pytest.mark.parametrize(
    ("task_kind", "title", "last_summary", "expected"),
    [
        ("work", "优化共享记忆管理界面", "完成了第一轮信息架构收敛。", True),
        ("meta", "共享记忆系统这个任务的下一步是什么", "共享记忆系统这个任务的下一步是什么", False),
        ("system", "[cron] daily monitor", "NO_REPLY", False),
        ("work", "", "", False),
    ],
)
def test_should_materialize_task_respects_kind_and_content(
    task_kind: str,
    title: str,
    last_summary: str,
    expected: bool,
):
    assert (
        should_materialize_task(
            task_kind=task_kind,
            title=title,
            last_summary=last_summary,
        )
        is expected
    )
