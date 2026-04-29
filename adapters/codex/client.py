from __future__ import annotations

from typing import Any

import httpx

from config import load_config


class AutomemClient:
    def __init__(self) -> None:
        self._config = load_config()
        self._client = httpx.Client(
            base_url=self._config.memory_url,
            headers={"X-API-Key": self._config.memory_api_key},
            timeout=30.0,
            trust_env=False,
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
        response = self._client.get("/v1/healthz")
        response.raise_for_status()
        return response.json()

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
        payload = {"query": query, "user_id": user_id}
        if agent_id:
            payload["agent_id"] = agent_id
        if run_id:
            payload["run_id"] = run_id
        if filters:
            payload["filters"] = filters
        if limit is not None:
            payload["limit"] = limit
        response = self._client.post("/v1/search", json=payload)
        response.raise_for_status()
        return response.json()

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
        response = self._client.post("/v1/memories", json=payload)
        response.raise_for_status()
        return response.json()

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
        response = self._client.get("/v1/memories", params=params)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                return results
        if isinstance(payload, list):
            return payload
        raise TypeError(f"Unexpected /memories payload shape: {type(payload).__name__}")

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        response = self._client.get(f"/v1/memories/{memory_id}")
        response.raise_for_status()
        return response.json()

    def forget(self, memory_id: str) -> dict[str, Any]:
        response = self._client.delete(f"/v1/memories/{memory_id}")
        response.raise_for_status()
        return response.json()

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
        response = self._client.post("/v1/task-resolution", json=payload)
        response.raise_for_status()
        return response.json()

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
        payload: dict[str, Any] = {"user_id": user_id}
        for key, value in {
            "agent_id": agent_id,
            "project_id": project_id,
            "task_id": task_id,
            "title": title,
            "summary": summary,
            "progress": progress,
            "blocker": blocker,
            "next_action": next_action,
            "message": message,
            "assistant_output": assistant_output,
            "session_id": session_id,
            "channel": channel,
        }.items():
            if value is not None:
                payload[key] = value
        response = self._client.post("/v1/task-summaries", json=payload)
        response.raise_for_status()
        return response.json()

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
        response = self._client.post("/v1/memory-route", json=payload)
        response.raise_for_status()
        return response.json()

    def list_tasks(
        self,
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
        response = self._client.get("/v1/tasks", params=params)
        response.raise_for_status()
        return response.json()

    def get_task(self, task_id: str) -> dict[str, Any]:
        response = self._client.get(f"/v1/tasks/{task_id}")
        response.raise_for_status()
        return response.json()

    def close_task(self, task_id: str, *, reason: str | None = None) -> dict[str, Any]:
        response = self._client.post(f"/v1/tasks/{task_id}/close", json={"reason": reason})
        response.raise_for_status()
        return response.json()

    def archive_task(self, task_id: str, *, reason: str | None = None) -> dict[str, Any]:
        response = self._client.post(f"/v1/tasks/{task_id}/archive", json={"reason": reason})
        response.raise_for_status()
        return response.json()

    def metrics(self) -> dict[str, Any]:
        response = self._client.get("/v1/metrics")
        if response.status_code != 403:
            response.raise_for_status()
            return response.json()

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
        response = self._client.post(
            "/v1/consolidate",
            json={
                "dry_run": dry_run,
                "dedupe_long_term": True,
                "archive_closed_tasks": True,
            },
        )
        response.raise_for_status()
        return response.json()
