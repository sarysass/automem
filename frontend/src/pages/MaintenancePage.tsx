import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import type { ConsolidateResponse } from "@/lib/types";

export function MaintenancePage() {
  const [userId, setUserId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [consolidateResult, setConsolidateResult] = useState<ConsolidateResponse | null>(null);
  const [cacheResult, setCacheResult] = useState<{ rebuilt: number; user_id?: string } | null>(null);
  const [error, setError] = useState("");

  async function handleConsolidate(event: FormEvent) {
    event.preventDefault();
    try {
      setError("");
      setCacheResult(null);
      const response = await api.consolidate({
        dry_run: true,
        user_id: userId || undefined,
        project_id: projectId || undefined,
      });
      setConsolidateResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "整理失败");
    }
  }

  async function handleRebuildCache() {
    try {
      setError("");
      setConsolidateResult(null);
      const response = await api.rebuildCache({ user_id: userId || undefined });
      setCacheResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "缓存重建失败");
    }
  }

  return (
    <section className="page-stack">
      <div className="section-heading">
        <div>
          <h3>维护操作</h3>
          <p>保留整理预演与缓存重建两个高价值操作。</p>
        </div>
      </div>

      <form className="filter-grid compact" onSubmit={handleConsolidate}>
        <label>
          用户 ID
          <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="全部用户" />
        </label>
        <label>
          项目 ID
          <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="全部项目" />
        </label>
        <div className="filter-actions">
          <button type="submit">执行整理预演</button>
          <button type="button" className="secondary" onClick={() => void handleRebuildCache()}>
            重建缓存
          </button>
        </div>
      </form>

      {error ? <p className="error-text">{error}</p> : null}

      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-title">整理结果</div>
          {consolidateResult ? (
            <div className="kv-grid">
              <div className="kv-item"><span>重复长期记忆</span><strong>{consolidateResult.duplicate_long_term_count}</strong></div>
              <div className="kv-item"><span>归档任务数</span><strong>{consolidateResult.archived_tasks_count}</strong></div>
              <div className="kv-item"><span>用户范围</span><strong>{consolidateResult.user_id || "全部"}</strong></div>
              <div className="kv-item"><span>项目范围</span><strong>{consolidateResult.project_id || "全部"}</strong></div>
            </div>
          ) : (
            <p className="empty-text">尚未执行整理预演。</p>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">缓存结果</div>
          {cacheResult ? (
            <div className="kv-grid">
              <div className="kv-item"><span>重建条数</span><strong>{cacheResult.rebuilt}</strong></div>
              <div className="kv-item"><span>用户范围</span><strong>{cacheResult.user_id || "全部"}</strong></div>
            </div>
          ) : (
            <p className="empty-text">尚未执行缓存重建。</p>
          )}
        </section>
      </div>
    </section>
  );
}
