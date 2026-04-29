"""Pure payload constructors. No HTTP, no env lookup.

Adapters can call these to build a request body, then inspect or mutate it
before sending. This keeps the wire format consistent across CLI, codex MCP,
and claude-code hooks without forcing all of them through the same call shape.
"""

from __future__ import annotations

from typing import Any


def memory_route_payload(
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
    payload: dict[str, Any] = {"user_id": user_id, "message": message}
    for key, value in {
        "agent_id": agent_id,
        "project_id": project_id,
        "assistant_output": assistant_output,
        "session_id": session_id,
        "channel": channel,
        "client_hints": client_hints,
    }.items():
        if value is not None:
            payload[key] = value
    return payload


def store_long_term_payload(
    *,
    text: str,
    user_id: str,
    agent_id: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    metadata_extra: dict[str, Any] | None = None,
    infer: bool = False,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"domain": "long_term"}
    if category is not None:
        metadata["category"] = category
    if project_id is not None:
        metadata["project_id"] = project_id
    if agent_id is not None:
        metadata["source_agent"] = agent_id
    if metadata_extra:
        metadata.update(metadata_extra)
    return {
        "messages": [{"role": "user", "content": text}],
        "user_id": user_id,
        "infer": infer,
        "metadata": metadata,
    }


def store_task_summary_payload(
    *,
    user_id: str,
    task_id: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    progress: str | None = None,
    blocker: str | None = None,
    next_action: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    message: str | None = None,
    assistant_output: str | None = None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"user_id": user_id}
    for key, value in {
        "task_id": task_id,
        "title": title,
        "summary": summary,
        "progress": progress,
        "blocker": blocker,
        "next_action": next_action,
        "agent_id": agent_id,
        "project_id": project_id,
        "message": message,
        "assistant_output": assistant_output,
        "session_id": session_id,
        "channel": channel,
    }.items():
        if value is not None:
            payload[key] = value
    return payload


def search_payload(
    *,
    query: str,
    user_id: str,
    agent_id: str | None = None,
    run_id: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "user_id": user_id}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    if run_id is not None:
        payload["run_id"] = run_id
    if filters:
        payload["filters"] = filters
    if limit is not None:
        payload["limit"] = limit
    return payload


def list_tasks_params(
    *,
    user_id: str,
    project_id: str | None = None,
    status: str | None = "active",
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"user_id": user_id}
    if project_id is not None:
        params["project_id"] = project_id
    if status is not None:
        params["status"] = status
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor
    return params
