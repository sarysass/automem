import { FormEvent, useState } from "react";
import { api } from "@/lib/api";
import type { SearchMemoryResult } from "@/lib/types";

const DOMAIN_OPTIONS = [
  { value: "long_term", label: "长期记忆" },
  { value: "task", label: "任务记忆" },
  { value: "agent", label: "Agent 记忆" },
  { value: "", label: "全部域" },
];

const CATEGORY_OPTIONS = [
  { value: "", label: "全部分类" },
  { value: "user_profile", label: "用户资料" },
  { value: "preference", label: "用户偏好" },
  { value: "project_context", label: "项目背景" },
  { value: "project_rule", label: "项目规则" },
  { value: "architecture_decision", label: "架构决策" },
  { value: "handoff", label: "交接" },
  { value: "progress", label: "进展" },
  { value: "blocker", label: "阻塞" },
  { value: "next_action", label: "下一步" },
];

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [userId, setUserId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [category, setCategory] = useState("");
  const [domain, setDomain] = useState("long_term");
  const [results, setResults] = useState<SearchMemoryResult[]>([]);
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      setError("");
      setHasSearched(true);
      const filters: { project_id?: string; category?: string; domain?: string } = {};
      if (projectId) filters.project_id = projectId;
      if (category) filters.category = category;
      if (domain) filters.domain = domain;
      const payload =
        Object.keys(filters).length === 0
          ? { query, user_id: userId || undefined }
          : { query, user_id: userId || undefined, filters };
      const response = await api.search(payload);
      setResults(response.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "查询失败");
    }
  }

  return (
    <section className="page-stack">
      <div className="section-heading">
        <div>
          <h3>记忆检索</h3>
          <p>默认优先检索长期记忆。需要查任务时，再切换到任务记忆。</p>
        </div>
      </div>

      <form className="filter-grid" onSubmit={handleSubmit}>
        <label>
          查询词
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：我的名字叫什么 / 公司是哪个" />
        </label>
        <label>
          用户 ID
          <input value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="可选" />
        </label>
        <label>
          项目 ID
          <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="可选" />
        </label>
        <label>
          分类
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Domain
          <select value={domain} onChange={(event) => setDomain(event.target.value)}>
            {DOMAIN_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <div className="filter-actions">
          <button type="submit">查询</button>
        </div>
      </form>

      {error ? <p className="error-text">{error}</p> : null}

      <section className="panel">
        <div className="panel-title">结果列表</div>
        {results.length === 0 ? (
          <p className="empty-text">{hasSearched ? "已查询，但没有匹配结果。" : "尚未查询。默认先从长期记忆开始查。"}</p>
        ) : null}
        <div className="result-list">
          {results.map((item) => (
            <article key={item.id} className="result-card">
              <div className="pill-row">
                <span className="pill">{item.metadata?.category ?? "memory"}</span>
                <span className="pill">{item.metadata?.domain ?? "unknown"}</span>
                {item.metadata?.project_id ? <span className="pill">{item.metadata.project_id}</span> : null}
              </div>
              <p className="result-text">{item.memory ?? item.text ?? ""}</p>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
