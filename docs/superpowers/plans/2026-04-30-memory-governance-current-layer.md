# 记忆治理 Current Layer 实施计划

> **给 agentic worker 的要求：** 执行本计划时需要使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项执行并更新 checkbox 状态。

**目标：** 让定时治理真正把过期的项目过程记忆从默认 active recall 中移走，同时保留“当前项目状态”这类有用事实，并让新事实自动覆盖旧事实。

**架构：** 新增一个很小的项目记忆生命周期分类器，供 fact-key 推断和离线 consolidate 共同使用。描述当前状态的项目记忆会获得稳定的 `project_context:*` fact key，并能 supersede 旧版本；Phase、plan、review、progress 这类过程日志会在 consolidate 时归档为 `superseded`，默认搜索不再召回。

**技术栈：** Python 3.13、FastAPI、SQLite `memory_cache`、mem0 兼容后端、pytest、现有 governance service 层。

---

## 文件结构

- 新增 `backend/governance/project_lifecycle.py`
  - 负责项目上下文记忆的生命周期启发式规则。
  - 暴露 `infer_project_context_fact_key()` 和 `is_archivable_project_context_process_log()`。
- 修改 `backend/memory_cache.py`
  - 对 `project_context` 使用新的生命周期 fact-key 推断。
  - 把项目当前状态相关 fact key 加入 auto-supersede 白名单。
- 修改 `backend/services.py`
  - 在 `run_consolidation_operation()` 中归档 active long-term 的 `project_context` 过程日志。
  - 返回新增指标 `archived_project_context_count`。
- 修改 `scripts/governance_worker.py`
  - worker 在有 `MEMORY_URL` 时走 HTTP `/v1/governance/jobs/run-next`，避免测试/运行时子进程误创建真实 mem0/Ollama 后端。
  - direct in-process 路径仍保留，并显式传入 `memory_backend`。
- 修改 `tests/support/runtime_drivers.py`
  - 给 runtime 子进程注入测试用 fake ZAI 环境，避免 `backend.main` 初始化因为缺少 `ZAI_API_KEY` 失败。
- 修改 `tests/test_backend_baseline.py`
  - 增加当前项目状态 supersede 和过程日志归档的回归测试。
- 修改 `tests/test_governance_worker.py`
  - 同步 worker direct dispatch 的新依赖注入接口。

## 设计说明

默认召回应当偏向“现在仍然成立的事实”，而不是完整过程流水账。历史过程记录不删除，只标记成 `superseded`，这样需要查历史时仍可通过 history/status 查询拿到。

这次刻意不做大规模语义清理，也不依赖 LLM 判断。第一阶段只做确定性、可测试、可上线的窄切口，直接解决已经观察到的问题：大量旧 `project_context` 过程记录还停留在 active recall 里。

## Task 1：为“当前项目状态”增加稳定 fact key

**涉及文件：**
- 新增：`backend/governance/project_lifecycle.py`
- 修改：`backend/memory_cache.py`
- 测试：`tests/test_backend_baseline.py`

### Step 1：先写失败测试

在 `tests/test_backend_baseline.py` 中增加测试：

```python
def test_project_current_state_memory_supersedes_previous_active_fact(client, auth_headers):
    first = add_long_term_memory(
        client,
        auth_headers,
        text="Automem current memory-governance state: old policy leaves process logs active",
        user_id="user-a",
        category="project_context",
    )
    first_id = first["results"][0]["id"]

    second = add_long_term_memory(
        client,
        auth_headers,
        text="Automem current memory-governance state: daily consolidate archives stale process logs",
        user_id="user-a",
        category="project_context",
    )

    assert second["fact_status"] == "active"
    assert second["fact_action"] == "superseded"
    assert second["superseded_memory_ids"] == [first_id]
```

运行：

```bash
uv run pytest tests/test_backend_baseline.py::test_project_current_state_memory_supersedes_previous_active_fact -q
```

预期失败：第二条 `project_context` 只是普通 `stored`，没有 supersede 第一条。

实际红灯结果：

```text
AssertionError: assert 'stored' == 'superseded'
```

### Step 2：新增项目生命周期分类器

新增 `backend/governance/project_lifecycle.py`：

```python
PROJECT_CURRENT_FACT_KEYS = {
    "project_context:current_state",
    "project_context:current_deployment_state",
    "project_context:current_next_action",
    "project_context:current_risks",
}
```

核心规则：

- 包含 `current/currently/now/当前/目前/现在/现状` -> `project_context:current_state`
- 包含 `vps/gc-jp/systemd/timer/worker/service/deploy/部署/定时/服务` -> `project_context:current_deployment_state`
- 包含 `next action/next step/todo/blocker/下一步/接下来/阻塞` -> `project_context:current_next_action`
- 包含 `risk/concern/problem/issue/unsafe/dissatisfied/风险/问题/不满意` -> `project_context:current_risks`

### Step 3：接入 fact-key 推断和 auto-supersede

在 `backend/memory_cache.py` 中：

- 引入 `PROJECT_CURRENT_FACT_KEYS` 和 `infer_project_context_fact_key`
- 把 `PROJECT_CURRENT_FACT_KEYS` 加入 `AUTO_SUPERSEDE_FACT_KEYS`
- 在 `infer_long_term_fact_key()` 的 `project_context` 分支中优先调用 `infer_project_context_fact_key()`

### Step 4：验证 Task 1 通过

运行：

```bash
uv run pytest tests/test_backend_baseline.py::test_project_current_state_memory_supersedes_previous_active_fact -q
```

预期并实际通过：

```text
. [100%]
```

## Task 2：consolidate 时归档过期项目过程日志

**涉及文件：**
- 修改：`backend/services.py`
- 测试：`tests/test_backend_baseline.py`

### Step 1：先写失败测试

新增测试 `test_consolidate_archives_project_context_process_logs_without_deleting_history`，构造三条记忆：

- 旧过程日志：`Phase 07 completed: validation passed for an older routing rollout`
- 旧过程日志：`Phase 08 progress: research notes and review checklist were captured`
- 当前部署事实：`gc-jp VPS currently runs automem-consolidate.timer daily at 03:30`

测试目标：

- `/v1/consolidate` 返回 `archived_project_context_count == 2`
- 两条 Phase/progress 过程日志不再处于 active
- 当前部署事实仍处于 active
- 两条旧过程日志仍在历史里，状态为 `superseded`
- `superseded_by == "consolidation:project_context_process_log"`

运行：

```bash
uv run pytest tests/test_backend_baseline.py::test_consolidate_archives_project_context_process_logs_without_deleting_history -q
```

预期失败：返回里没有 `archived_project_context_count`，旧过程记忆仍为 active。

实际红灯结果：

```text
KeyError: 'archived_project_context_count'
```

### Step 2：实现归档逻辑

在 `backend/services.py` 的 `run_consolidation_operation()` 中：

- 初始化 `archived_project_context_count = 0`
- 在扫描 active long-term facts 时调用 `is_archivable_project_context_process_log()`
- 对命中的项目过程日志调用既有 `archive_active_long_term_facts()` 路径
- 使用固定 superseded 标记：

```python
"consolidation:project_context_process_log"
```

- 返回新增指标：

```python
"archived_project_context_count": archived_project_context_count
```

### Step 3：验证 Task 2 通过

运行：

```bash
uv run pytest tests/test_backend_baseline.py::test_consolidate_archives_project_context_process_logs_without_deleting_history -q
```

预期并实际通过：

```text
. [100%]
```

## Task 3：修复 worker runtime 验证路径

**触发原因：** 默认全量测试 `uv run pytest` 暴露两个 live runtime 失败。最初是 worker 子进程缺 `ZAI_API_KEY`，补上测试环境后又暴露 worker 子进程会创建真实 mem0/Ollama 后端并尝试连 `127.0.0.1:11434`。

### Step 1：确认失败

运行：

```bash
uv run pytest
```

初始失败：

```text
Worker loop failed: 'ZAI_API_KEY'
```

补齐 fake ZAI 环境后继续失败：

```text
Worker loop failed: (status code: 502)
HTTP Request: GET http://127.0.0.1:11434/api/tags "HTTP/1.1 502 Bad Gateway"
```

### Step 2：修复 runtime driver 环境

在 `tests/support/runtime_drivers.py` 的 `_base_runtime_env()` 中加入：

```python
"ZAI_API_KEY": "test-zai-key",
"ZAI_BASE_URL": "https://example.invalid",
"ZAI_MODEL": "glm-test",
```

### Step 3：修复 worker 执行路径

在 `scripts/governance_worker.py` 中：

- 新增 `build_base_url()`
- 新增 `run_once_via_http()`
- 当环境里存在 `MEMORY_URL` 时，worker 通过 HTTP 调用：

```text
POST /v1/governance/jobs/run-next
```

这样 live backend 仍使用测试进程配置好的 FakeMemory，而 worker 子进程不会误创建真实 mem0/Ollama 后端。

direct in-process 路径保留，用于没有 `MEMORY_URL` 的生产/本机 worker 场景。

### Step 4：同步 worker 单元测试

在 `tests/test_governance_worker.py` 中：

- fake `_import_backend_dispatch()` 从三元组更新为四元组：

```python
(claim, dispatch, get_memory_backend, ensure_db)
```

- fake `dispatch()` 增加 `memory_backend` 参数断言。

### Step 5：验证 worker 路径通过

运行：

```bash
uv run pytest tests/test_runtime_drivers.py::test_worker_driver_returns_run_next_payload tests/test_runtime_entrypoints_live.py::test_worker_run_next_processes_job_and_updates_metrics_and_audit tests/test_governance_worker.py -q
```

预期并实际通过：

```text
........ [100%]
```

## Task 4：回归验证

### Focused governance 测试

运行：

```bash
uv run pytest tests/test_backend_baseline.py::test_project_current_state_memory_supersedes_previous_active_fact tests/test_backend_baseline.py::test_consolidate_archives_project_context_process_logs_without_deleting_history tests/test_backend_baseline.py::test_consolidate_supersedes_legacy_active_fact_versions tests/test_backend_baseline.py::test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks -q
```

结果：

```text
.... [100%]
```

### Scheduled consolidate 测试

运行：

```bash
uv run pytest tests/test_scheduled_consolidate.py -q
```

结果：

```text
........ [100%]
```

### 相邻 memory/task governance 测试

运行：

```bash
uv run pytest tests/test_deep_user_memory_flows.py tests/test_task_governance_targets.py -q
```

结果：

```text
................. [100%]
```

### Backend baseline 全文件

运行：

```bash
uv run pytest tests/test_backend_baseline.py -q
```

结果：

```text
全部通过，含 2 个 skipped
```

### 全量默认测试

运行：

```bash
uv run pytest
```

结果：

```text
192 passed, 2 skipped
```

### Ruff

运行：

```bash
uv run ruff check backend/governance/project_lifecycle.py backend/memory_cache.py backend/services.py scripts/governance_worker.py tests/test_backend_baseline.py tests/test_governance_worker.py tests/support/runtime_drivers.py
```

结果：

```text
All checks passed!
```

## 已完成效果

1. 新的“当前项目状态”记忆会稳定落到 `project_context:current_state` 等 fact key 上。
2. 新的当前状态会自动 supersede 旧的当前状态。
3. 每日 consolidate 现在会把 Phase/plan/review/progress 等项目过程日志从 active 归档到 superseded。
4. 历史过程记录不删除，仍可通过 history/status 查询。
5. worker runtime 测试路径不再误连真实 mem0/Ollama。
6. 全量测试通过。
