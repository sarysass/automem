---
status: passed
phase: 02-centralize-memory-governance
requirements: [GOV-01]
completed: 2026-04-16
---

# Phase 02 Verification

## Outcome

Phase 02 passes automated verification.

## Requirements Coverage

### GOV-01 Backend-Owned Governance

- `backend/main.py` 中的 `route_memory`、`store_memory_with_governance` 和 `/memory-route` 端点把长期记忆与 task admission 的治理判断收口在 backend，而不是由 adapter 本地拍板。
- `tests/test_backend_baseline.py` 里的 `test_add_memory_rejects_task_noise_markers`、`test_add_memory_rejects_transport_metadata_noise`、`test_memory_route_drops_time_scaffold`、`test_memory_route_does_not_materialize_task_rows` 证明 backend 会主动丢弃 task noise、transport metadata noise，并阻止路由结果在错误场景下 materialize 成 task rows。
- `tests/test_adapter_regressions.py` 里的 `test_claude_capture_commits_duplicate_state_only_after_success` 证明 adapter 只有在 backend 路由成功返回后才会提交本地 duplicate state，不会把本地 capture 判定当成最终治理结果。
- 当前接入代码也都明确指向 backend 路由入口：`.planning/phases/02-centralize-memory-governance/02-VERIFICATION.md` 依赖的证据来自 `adapters/claude-code/scripts/common.py`、`adapters/codex/mcp_server.py`、`adapters/openclaw/index.ts` 中对 `/memory-route` 的调用。

## Automated Evidence

- `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_add_memory_rejects_task_noise_markers tests/test_backend_baseline.py::test_add_memory_rejects_transport_metadata_noise tests/test_backend_baseline.py::test_memory_route_drops_time_scaffold tests/test_backend_baseline.py::test_memory_route_does_not_materialize_task_rows tests/test_adapter_regressions.py::test_claude_capture_commits_duplicate_state_only_after_success`
  Result: `5 passed in 0.32s`

## Must-Haves

- [x] 长期记忆与 task admission 的治理判断由 backend 集中执行。
- [x] adapter 不会把本地 capture 猜测直接当成最终治理结果写回系统。
- [x] task noise、transport metadata noise 和错误 task materialization 都有回归测试覆盖。

## Gaps

None.

## Human Verification

None required.
