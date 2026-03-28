import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { HealthResponse, MetricsResponse } from "@/lib/types";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { useSessionStore } from "@/stores/sessionStore";

export function DashboardPage() {
  const apiKey = useSessionStore((state) => state.apiKey);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setError("");
      const [healthData, metricsData] = await Promise.all([api.health(), api.metrics()]);
      setHealth(healthData);
      setMetrics(metricsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, [apiKey]);

  useAutoRefresh(refresh, [refresh]);

  const routeEntries = Object.entries(metrics?.metrics.routes ?? {});
  const eventEntries = Object.entries(metrics?.metrics.events ?? {});

  return (
    <section className="page-stack">
      <div className="section-heading">
        <div>
          <h3>仪表盘</h3>
          <p>进入页面后自动刷新系统状态与平台指标。</p>
        </div>
        <button onClick={() => void refresh()}>刷新</button>
      </div>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="stats-grid dashboard-top-grid">
        <article className="stat-card stat-card-primary">
          <span className="stat-label">状态</span>
          <strong>{health?.ok ? "正常运行" : "等待检测"}</strong>
          <p>LLM · {health?.llm_model ?? "-"}</p>
        </article>
        <article className="stat-card stat-card-secondary">
          <span className="stat-label">检索基础设施</span>
          <strong>{health?.embed_model ?? "-"}</strong>
          <p>Qdrant · {health?.qdrant ?? "-"}</p>
        </article>
        <article className="stat-card stat-card-metric">
          <span className="stat-label">活跃任务</span>
          <strong>{metrics?.metrics.tasks?.active ?? 0}</strong>
          <p>已归档 {metrics?.metrics.tasks?.archived ?? 0}</p>
        </article>
        <article className="stat-card stat-card-metric">
          <span className="stat-label">缓存条数</span>
          <strong>{metrics?.metrics.memory_cache?.entries ?? 0}</strong>
          <p>Task DB 已连接</p>
        </article>
      </div>

      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-title">路由分布</div>
          <div className="pill-row">
            {routeEntries.length === 0 ? <span className="empty-text">暂无路由数据</span> : null}
            {routeEntries.map(([key, value]) => (
              <span key={key} className="pill">
                {key} · {value}
              </span>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">事件统计</div>
          <div className="pill-row">
            {eventEntries.length === 0 ? <span className="empty-text">暂无事件数据</span> : null}
            {eventEntries.map(([key, value]) => (
              <span key={key} className="pill">
                {key} · {value}
              </span>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
