---
phase: 07-runtime-architecture-upgrade
plan: 01
subsystem: runtime
tags: [runtime-architecture, governance-worker, hot-path-api, job-queue, observability, fastapi, testing]
requires:
  - phase: 03-stabilize-cache-and-consolidation
    provides: safe consolidation flow, cache refresh, and scheduler hardening baseline
  - phase: 06-temporal-facts-and-conflict-governance
    provides: fact lifecycle semantics that background governance must preserve
provides:
  - governance job queue with idempotency, leasing, and retry recovery
  - worker entrypoint for background governance execution
  - runtime topology contract for API, worker, and MCP responsibilities
  - worker-aware scheduled consolidation flow and queue metrics
affects: [backend, scripts, docs, adapters]
tech-stack:
  added: []
  patterns: [hot-path api, sqlite job queue, lease-based worker recovery, runtime topology endpoint]
key-files:
  created: [scripts/governance_worker.py, tests/test_governance_worker.py, .planning/phases/07-runtime-architecture-upgrade/07-VERIFICATION.md]
  modified: [backend/main.py, scripts/scheduled_consolidate.py, tests/test_backend_baseline.py, tests/test_scheduled_consolidate.py, docs/ARCHITECTURE.md, docs/INTEGRATIONS.md, adapters/README.zh-CN.md, README.md]
key-decisions:
  - "Hot path keeps route, admission, retrieval, and task resolution synchronous, while heavy cleanup is submitted as governance jobs."
  - "Background governance uses sqlite-backed idempotent jobs with lease expiry so stale running work can be recovered safely."
patterns-established:
  - "Operational scripts enqueue work through API-owned job contracts instead of embedding cleanup logic directly in cron callers."
  - "Runtime topology is now a first-class API surface so adapters can stay thin and treat the backend plus worker as the source of truth."
requirements-completed: [OPS-01, OPS-02]
duration: 1 session
completed: 2026-04-16
---

# Phase 07: Runtime Architecture Upgrade Summary

**automem 现在把同步 hot path、后台治理 worker 和 MCP/adapters 的职责拆清楚了：API 负责准入与查询，worker 负责重治理，adapter 只做控制面接入**

## Performance

- **Duration:** 1 session
- **Completed:** 2026-04-16
- **Tasks:** 5
- **Files modified:** 10

## Accomplishments

- 在 `backend/main.py` 中新增 `governance_jobs` 队列表、作业 claim/lease/retry 逻辑，以及 `POST /governance/jobs`、`POST /governance/jobs/run-next`、`GET /governance/jobs*` 等后台治理接口。
- 将 consolidation 主逻辑抽成共享执行函数，让 API inline 执行和 background worker 执行共用同一套结果与审计字段，并显式返回 `runtime_path`、`worker_id`、`job_id`。
- 增加 `/runtime-topology` 与增强版 `/healthz` / `/metrics`，把 API、worker、MCP 的职责分工和治理队列状态暴露为结构化运行时信息。
- 将 `scripts/scheduled_consolidate.py` 从“直接调用 `/consolidate`”升级为默认 enqueue consolidate 作业，并支持 bucketed idempotency key。
- 新增 `scripts/governance_worker.py`，提供后台治理 worker 的 one-shot / polling 入口和单实例锁。

## Files Created/Modified

- `backend/main.py` - 新增治理作业队列、worker 执行流、运行时拓扑与队列指标，并把 consolidation 提炼为可复用后台任务。
- `scripts/scheduled_consolidate.py` - 默认改为提交 consolidate 作业到治理队列，同时保留 inline 兼容模式。
- `scripts/governance_worker.py` - 新增后台治理 worker 脚本，负责消费 `/governance/jobs/run-next`。
- `tests/test_backend_baseline.py` - 新增 runtime topology、治理队列执行、作业幂等的 API 回归测试。
- `tests/test_scheduled_consolidate.py` - 调整为覆盖 enqueue 模式、作业响应校验和 bucketed idempotency key。
- `tests/test_governance_worker.py` - 新增 worker 入口和锁行为测试。
- `docs/ARCHITECTURE.md`、`docs/INTEGRATIONS.md`、`adapters/README.zh-CN.md`、`README.md` - 记录 API + worker + MCP 的运行时边界和部署方式。

## Decisions Made

- Consolidation 和类似重治理动作属于后台治理，不再默认让定时脚本或 adapter 直接持有完整执行逻辑。
- API 继续保留 `/consolidate` 作为管理员可直接调用的 inline 入口，但后台 worker 通过相同核心逻辑执行，避免两套语义漂移。

## Deviations from Plan

- 这一阶段优先落地最小可用的后台治理作业类型 `consolidate`，而不是一次性把所有潜在重治理动作都拆成独立 worker job。

## Issues Encountered

- `git diff --check` 在文档阶段暴露了一处尾随空格，已清理。
- 为了避免运行时语义分叉，最终选择让 worker 和 inline consolidate 共用同一核心函数，而不是复制一份专门的 worker 版本。

## User Setup Required

- 如需启用后台治理 worker，请运行 `python scripts/governance_worker.py`。
- 如果保留 cron 调度，`scripts/scheduled_consolidate.py` 现在默认只 enqueue 作业；真正执行需要 worker 进程在线。

## Next Phase Readiness

Phase 07 完成后，当前里程碑里的运行时职责已经明确：

- API 负责同步准入、查询与作业提交
- Worker 负责后台治理执行
- MCP / adapters 负责工具暴露和 recall/capture 接入

当前没有阻塞本里程碑收尾的技术缺口。

---
*Phase: 07-runtime-architecture-upgrade*
*Completed: 2026-04-16*
