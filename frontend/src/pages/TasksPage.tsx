import { FormEvent, useCallback, useState } from "react";
import { api } from "@/lib/api";
import type { TaskRecord } from "@/lib/types";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { useSessionStore } from "@/stores/sessionStore";

export function TasksPage() {
  const apiKey = useSessionStore((state) => state.apiKey);
  const [userId, setUserId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("active");
  const [showSystemTasks, setShowSystemTasks] = useState(false);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setError("");
      const response = await api.tasks({
        userId: userId || undefined,
        projectId: projectId || undefined,
        status: status || undefined,
        limit: 50,
      });
      setTasks(response.tasks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务加载失败");
    }
  }, [apiKey, projectId, status, userId]);

  useAutoRefresh(refresh, [refresh]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void refresh();
  }

  const visibleTasks = showSystemTasks ? tasks : tasks.filter((task) => (task.task_kind ?? "work") === "work");

  return (
    <section className="page-stack">
      <div className="section-heading">
        <div>
          <h3>任务列表</h3>
          <p>进入页面自动刷新，默认优先显示工作任务。系统巡检与元信息任务可按需展开。</p>
        </div>
        <button onClick={() => void refresh()}>刷新</button>
      </div>

      <form className="filter-grid compact task-filter-grid" onSubmit={handleSubmit}>
        <label>
          用户 ID
          <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="全部用户" />
        </label>
        <label>
          项目 ID
          <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="全部项目" />
        </label>
        <label>
          状态
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="active">active</option>
            <option value="closed">closed</option>
            <option value="archived">archived</option>
          </select>
        </label>
        <div className="filter-actions filter-actions-inline">
          <button type="submit">应用筛选</button>
        </div>
      </form>

      <label className="inline-toggle">
        <input type="checkbox" checked={showSystemTasks} onChange={(event) => setShowSystemTasks(event.target.checked)} />
        显示系统任务与元信息任务
      </label>

      {error ? <p className="error-text">{error}</p> : null}

      <section className="panel">
        <div className="panel-title">任务概览</div>
        <div className="table-shell">
          <table className="data-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>类型</th>
                <th>状态</th>
                <th>项目</th>
                <th>Agent</th>
                <th>最近摘要</th>
              </tr>
            </thead>
            <tbody>
              {visibleTasks.map((task) => (
                <tr key={task.task_id}>
                  <td>{task.display_title || task.title || task.task_id}</td>
                  <td><span className="pill">{task.task_kind === "work" || !task.task_kind ? "工作任务" : task.task_kind === "system" ? "系统任务" : "元信息"}</span></td>
                  <td><span className="pill">{task.status}</span></td>
                  <td>{task.project_id || "-"}</td>
                  <td>{task.owner_agent || "-"}</td>
                  <td>{task.summary_preview || task.last_summary || "暂无摘要"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {visibleTasks.length === 0 ? <p className="empty-text">当前没有符合筛选条件的任务。</p> : null}
        </div>
      </section>
    </section>
  );
}
