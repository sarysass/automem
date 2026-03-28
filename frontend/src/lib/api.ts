import type { ConsolidateResponse, HealthResponse, MetricsResponse, SearchResponse, TasksResponse } from "@/lib/types";
import { useSessionStore } from "@/stores/sessionStore";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const apiKey = useSessionStore.getState().apiKey.trim();
  if (!apiKey) {
    throw new Error("请先填写管理 API Key");
  }
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

function buildTaskQuery(params: { userId?: string; projectId?: string; status?: string; limit?: number }) {
  const query = new URLSearchParams();
  if (params.userId) query.set("user_id", params.userId);
  if (params.projectId) query.set("project_id", params.projectId);
  if (params.status) query.set("status", params.status);
  if (params.limit) query.set("limit", String(params.limit));
  return query.toString();
}

export const api = {
  async health() {
    return requestJson<HealthResponse>("/v1/healthz");
  },
  async metrics() {
    return requestJson<MetricsResponse>("/v1/metrics");
  },
  async search(payload: {
    query: string;
    user_id?: string;
    filters?: { project_id?: string; category?: string; domain?: string };
  }) {
    return requestJson<SearchResponse>("/v1/search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async tasks(params: { userId?: string; projectId?: string; status?: string; limit?: number }) {
    const query = buildTaskQuery(params);
    return requestJson<TasksResponse>(`/v1/tasks${query ? `?${query}` : ""}`);
  },
  async consolidate(payload: { user_id?: string; project_id?: string; dry_run: boolean }) {
    return requestJson<ConsolidateResponse>("/v1/consolidate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  async rebuildCache(payload: { user_id?: string }) {
    return requestJson<{ rebuilt: number; user_id?: string; run_id?: string; agent_id?: string }>(
      "/v1/cache/rebuild",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
  },
};
