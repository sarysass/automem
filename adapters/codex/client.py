from __future__ import annotations

from typing import Any

import httpx

from automem_client import (
    build_client,
    decode,
    list_tasks_params,
    memory_route_payload,
    search_payload,
    store_task_summary_payload,
)
from config import load_config


class AutomemClient:
    def __init__(self) -> None:
        self._config = load_config()
        self._client = build_client(
            url=self._config.memory_url,
            key=self._config.memory_api_key,
            timeout=30.0,
        )

    @property
    def defaults(self) -> dict[str, Any]:
        return {
            "user_id": self._config.default_user_id,
            "agent_id": self._config.default_agent_id,
            "project_id": self._config.default_project_id,
            "search_threshold": self._config.search_threshold,
            "top_k": self._config.top_k,
        }

    def close(self) -> None:
        self._client.close()

    def healthz(self) -> dict[str, Any]:
        return decode(self._client.get("/v1/healthz"))

    def search(
        self,
        *,
        query: str,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        payload = search_payload(
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            filters=filters,
            limit=limit,
        )
        return decode(self._client.post("/v1/search", json=payload))

    def store(
        self,
        *,
        text: str,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        infer: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": text}],
            "user_id": user_id,
            "infer": infer,
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if run_id:
            payload["run_id"] = run_id
        if metadata:
            payload["metadata"] = metadata
        return decode(self._client.post("/v1/memories", json=payload))

    def list_memories(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"user_id": user_id}
        if agent_id:
            params["agent_id"] = agent_id
        if run_id:
            params["run_id"] = run_id
        payload = decode(self._client.get("/v1/memories", params=params))
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                return results
        if isinstance(payload, list):
            return payload
        raise TypeError(f"Unexpected /memories payload shape: {type(payload).__name__}")

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        return decode(self._client.get(f"/v1/memories/{memory_id}"))

    def forget(self, memory_id: str) -> dict[str, Any]:
        return decode(self._client.delete(f"/v1/memories/{memory_id}"))

    def resolve_task(
        self,
        *,
        user_id: str,
        message: str,
        agent_id: str | None = None,
        project_id: str | None = None,
        assistant_output: str | None = None,
        session_id: str | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"user_id": user_id, "message": message}
        for key, value in {
            "agent_id": agent_id,
            "project_id": project_id,
            "assistant_output": assistant_output,
            "session_id": session_id,
            "channel": channel,
        }.items():
            if value is not None:
                payload[key] = value
        return decode(self._client.post("/v1/task-resolution", json=payload))

    def store_task_summary(
        self,
        *,
        user_id: str,
        agent_id: str | None = None,
        project_id: str | None = None,
        task_id: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        progress: str | None = None,
        blocker: str | None = None,
        next_action: str | None = None,
        message: str | None = None,
        assistant_output: str | None = None,
        session_id: str | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        payload = store_task_summary_payload(
            user_id=user_id,
            task_id=task_id,
            title=title,
            summary=summary,
            progress=progress,
            blocker=blocker,
            next_action=next_action,
            agent_id=agent_id,
            project_id=project_id,
            message=message,
            assistant_output=assistant_output,
            session_id=session_id,
            channel=channel,
        )
        return decode(self._client.post("/v1/task-summaries", json=payload))

    def memory_route(
        self,
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
        return decode(self._client.post("/v1/memory-route", json=payload))

    def list_tasks(
        self,
        *,
        user_id: str,
        project_id: str | None = None,
        status: str | None = "active",
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        params = list_tasks_params(
            user_id=user_id,
            project_id=project_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
        return decode(self._client.get("/v1/tasks", params=params))

    def get_task(self, task_id: str) -> dict[str, Any]:
        return decode(self._client.get(f"/v1/tasks/{task_id}"))

    def close_task(self, task_id: str, *, reason: str | None = None) -> dict[str, Any]:
        return decode(self._client.post(f"/v1/tasks/{task_id}/close", json={"reason": reason}))

    def archive_task(self, task_id: str, *, reason: str | None = None) -> dict[str, Any]:
        return decode(self._client.post(f"/v1/tasks/{task_id}/archive", json={"reason": reason}))

    def metrics(self) -> dict[str, Any]:
        response = self._client.get("/v1/metrics")
        if response.status_code != 403:
            return decode(response)

        health = self.healthz()
        metrics = health.get("metrics")
        if isinstance(metrics, dict):
            return {"source": "healthz_fallback", **metrics}
        raise httpx.HTTPStatusError(
            "Client error '403 Forbidden' for url '/v1/metrics' and no metrics in /healthz fallback",
            request=response.request,
            response=response,
        )

    def consolidate(self, *, dry_run: bool = True) -> dict[str, Any]:
        return decode(
            self._client.post(
                "/v1/consolidate",
                json={
                    "dry_run": dry_run,
                    "dedupe_long_term": True,
                    "archive_closed_tasks": True,
                },
            )
        )
