export interface MetricsResponse {
  metrics: {
    routes?: Record<string, number>;
    events?: Record<string, number>;
    tasks?: { active?: number; archived?: number };
    memory_cache?: { entries?: number };
  };
}

export interface HealthResponse {
  ok: boolean;
  llm_model: string;
  embed_model: string;
  qdrant: string;
  task_db: string;
  metrics?: MetricsResponse["metrics"];
}

export interface SearchMemoryResult {
  id: string;
  memory?: string;
  text?: string;
  metadata?: Record<string, string | null | undefined>;
}

export interface SearchResponse {
  results: SearchMemoryResult[];
}

export interface TaskRecord {
  task_id: string;
  user_id: string;
  project_id?: string | null;
  title: string;
  display_title?: string | null;
  task_kind?: string | null;
  status: string;
  last_summary?: string | null;
  summary_preview?: string | null;
  owner_agent?: string | null;
  updated_at?: string | null;
}

export interface TasksResponse {
  tasks: TaskRecord[];
}

export interface ConsolidateResponse {
  dry_run: boolean;
  duplicate_long_term_count: number;
  archived_tasks_count: number;
  user_id?: string | null;
  project_id?: string | null;
}
