---
status: complete
phase: 11-deep-user-workflow-and-scope-regression
source: 11-01-SUMMARY.md, 11-02-SUMMARY.md, 11-03-SUMMARY.md, 11-04-SUMMARY.md
started: 2026-04-17T06:30:58Z
updated: 2026-04-17T06:35:36Z
---

## Current Test

[testing complete]

## Tests

### 1. 当前偏好检索优先返回最新事实
expected: 运行 `uv run pytest tests/test_deep_user_memory_flows.py -k intent_style_language_query_recalls_current_preference_in_top_three -x`。命令应通过，并且证明当用户先写入“偏好使用中文沟通”再写入“偏好使用英文沟通”后，查询“我应该用什么语言回复你”会把“偏好使用英文沟通”放进前 3 条结果里，同时默认结果中不再返回已 superseded 的中文偏好。
result: pass

### 2. 历史检索只在显式请求时暴露 superseded 和 conflict-review 事实
expected: 运行 `uv run pytest tests/test_deep_user_memory_flows.py -k 'supersede_story_keeps_current_first_and_exposes_history_trace or conflict_review_story_preserves_active_fact_until_history_is_requested' -x`。命令应通过，并且证明默认检索只返回当前 active 事实；只有显式打开 `include_history` 或按 `conflict_review` 过滤时，才会看到 superseded 或待审核冲突事实。
result: pass

### 3. 多跳任务接力后仍能找回同一个任务和下一步动作
expected: 运行 `uv run pytest tests/test_deep_user_task_flows.py -k multi_hop_handoff_keeps_task_identity_progress_and_next_action -x`。命令应通过，并且证明任务在多个 agent 交接后，`task_frontend-panel` 仍保持同一 task identity、active 状态、最新 summary，并且搜索“前端管理界面的下一步是什么”时能取回最新 next_action。
result: pass

### 4. 清理流程会归档系统噪音并保留真实工作
expected: 运行 `uv run pytest tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py -k 'layered_cleanup_archives_noise_and_prunes_old_non_work_without_hiding_real_work or non_work_task_summaries_do_not_materialize_tasks_or_task_memory' -x`。命令应通过，并且证明清理流程会把系统噪音任务归档或修剪掉，不会把真实工作任务隐藏，也不会把明显的 non-work 摘要错误地物化成 task/task memory。
result: pass

### 5. 项目作用域默认 fail-closed，管理员跨项目能力保留
expected: 运行 `uv run pytest tests/test_identity_e2e.py -k 'multi_project_key_requires_explicit_project or project_bound_memory_search_only_returns_allowed_project or project_bound_key_cannot_fetch_task_from_other_project or project_bound_key_cannot_close_task_from_other_project or project_bound_key_cannot_archive_task_from_other_project or admin' -x`。命令应通过，并且证明多项目 key 在未显式指定 project 时会被拒绝，project-bound key 只能看到自己允许的 project 数据，不能读取或修改其他项目任务，而管理员路径仍能跨项目读取和变更数据。
result: pass

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
