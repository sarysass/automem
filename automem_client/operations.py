"""High-level automem operations combining payload + HTTP call.

These wrap the standard memory-route → store flow so adapters can express
"capture this turn" or "search by query" in one line. Adapters that need
finer control should compose payloads + http themselves.
"""

from __future__ import annotations

from typing import Any

import httpx

from automem_client.http import decode
from automem_client.payloads import (
    list_tasks_params,
    memory_route_payload,
    search_payload,
    store_long_term_payload,
    store_task_summary_payload,
)


def search_memories(
    client: httpx.Client,
    *,
    query: str,
    user_id: str,
    agent_id: str | None = None,
    run_id: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    payload = search_payload(
        query=query,
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        filters=filters,
        limit=limit,
    )
    response = decode(client.post("/v1/search", json=payload))
    results = response.get("results")
    return results if isinstance(results, list) else []


def list_active_tasks(
    client: httpx.Client,
    *,
    user_id: str,
    project_id: str | None = None,
    status: str | None = "active",
    limit: int | None = None,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    params = list_tasks_params(
        user_id=user_id,
        project_id=project_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    response = decode(client.get("/v1/tasks", params=params))
    tasks = response.get("tasks")
    return tasks if isinstance(tasks, list) else []


def memory_route_request(
    client: httpx.Client,
    *,
    user_id: str,
    message: str,
    agent_id: str | None = None,
    project_id: str | None = None,
    assistant_output: str | None = None,
    session_id: str | None = None,
    channel: str | None = None,
    client_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = memory_route_payload(
        user_id=user_id,
        message=message,
        agent_id=agent_id,
        project_id=project_id,
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
        client_hints=client_hints,
    )
    return decode(client.post("/v1/memory-route", json=payload))


def capture_turn(
    client: httpx.Client,
    *,
    user_id: str,
    message: str,
    assistant_output: str | None,
    agent_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    channel: str | None = None,
    client_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route a turn, then store its long-term entries and task summary as appropriate."""
    routed = memory_route_request(
        client,
        user_id=user_id,
        message=message,
        agent_id=agent_id,
        project_id=project_id,
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
        client_hints=client_hints,
    )
    result: dict[str, Any] = {
        "route": routed.get("route"),
        "stored_long_term": [],
        "stored_task": None,
    }
    if routed.get("route") in {"long_term", "mixed"}:
        entries = routed.get("entries") or routed.get("long_term") or []
        for entry in entries:
            payload = store_long_term_payload(
                text=entry["text"],
                user_id=user_id,
                agent_id=agent_id,
                project_id=entry.get("project_id") or project_id,
                category=entry.get("category"),
            )
            result["stored_long_term"].append(decode(client.post("/v1/memories", json=payload)))
    if routed.get("route") in {"task", "mixed"} and routed.get("task"):
        task = routed["task"]
        summary = task.get("summary") or {}
        payload = store_task_summary_payload(
            user_id=user_id,
            task_id=task.get("task_id"),
            title=task.get("title"),
            summary=summary.get("summary"),
            progress=summary.get("progress"),
            blocker=summary.get("blocker"),
            next_action=summary.get("next_action"),
            agent_id=agent_id,
            project_id=project_id,
            message=message,
            assistant_output=assistant_output,
            session_id=session_id,
            channel=channel,
        )
        result["stored_task"] = decode(client.post("/v1/task-summaries", json=payload))
    return result
