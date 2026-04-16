---
status: passed
phase: 03-stabilize-cache-and-consolidation
requirements: [CONS-01, CONS-02]
completed: 2026-04-16
---

# Phase 03 Verification

## Outcome

Phase 03 passes automated verification.

## Requirements Coverage

### CONS-01 Fresh Cache Before Maintenance

- `backend/main.py` 的 `normalize_tasks(..., refresh_cache=True)` 在扫描 task state 前会先调用 `rebuild_memory_cache(...)`，保证维护流程不是基于陈旧 cache 运行。
- `backend/main.py` 的 consolidate 流程也会在执行维护前调用 `rebuild_memory_cache(...)`，并把新的 cache 状态作为去噪、去重和 task normalization 的输入。
- `tests/test_backend_baseline.py` 中的 `test_consolidate_respects_requested_user_scope`、`test_task_normalize_archives_non_work_items_and_rewrites_titles`、`test_cache_rebuild_restores_index_for_existing_memories`、`test_cache_rebuild_removes_stale_entries` 共同证明维护链路和 cache rebuild 结果是一致且可重复的。

### CONS-02 Safe Canonical Rewrite

- `backend/main.py` 的 consolidate rewrite loop 会先通过 memory backend 写入 replacement record，再在成功后删除旧记录；如果 rewrite 失败，会抛出异常并保留原始记录，不会先删后写。
- `scripts/scheduled_consolidate.py` 保留了 single-run lock、失败重试和 enqueue/inline 的明确返回校验，避免定时维护在重入或暂时失败时静默损坏状态。
- `tests/test_backend_baseline.py` 中的 `test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise`、`test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks`，以及 `tests/test_scheduled_consolidate.py` 中的 `test_run_consolidation_retries_before_success`、`test_main_skips_when_lock_exists` 覆盖了 rewrite、retry 和 lock 的关键路径。

## Automated Evidence

- `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_consolidate_respects_requested_user_scope tests/test_backend_baseline.py::test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise tests/test_backend_baseline.py::test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks tests/test_backend_baseline.py::test_task_normalize_archives_non_work_items_and_rewrites_titles tests/test_backend_baseline.py::test_cache_rebuild_restores_index_for_existing_memories tests/test_backend_baseline.py::test_cache_rebuild_removes_stale_entries tests/test_scheduled_consolidate.py::test_run_consolidation_retries_before_success tests/test_scheduled_consolidate.py::test_main_skips_when_lock_exists`
  Result: `8 passed in 0.42s`

## Must-Haves

- [x] 维护流程在 normalize / consolidate 前会刷新 cache。
- [x] canonical rewrite 使用先写后删的顺序，不会靠先删旧记录冒险。
- [x] 定时 consolidate 具备 lock 和 retry 保护，并有自动化测试证明。

## Gaps

None.

## Human Verification

None required.
