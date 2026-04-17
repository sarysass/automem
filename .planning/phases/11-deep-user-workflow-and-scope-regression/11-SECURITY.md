---
phase: 11-deep-user-workflow-and-scope-regression
audited_at: 2026-04-17T14:43:21+0800
audit_state: B
status: secured
asvs_level: 1
asvs_level_note: "Read from workflow.security_asvs_level in .planning/config.json."
block_on: high
threats_total: 8
threats_closed: 8
threats_open: 0
unregistered_flags: 0
---

# Phase 11 Security Audit

Artifact-driven mitigation audit for Phase 11 (`11-deep-user-workflow-and-scope-regression`).

- Audit state: `B` (no prior `11-SECURITY.md`; verified from plans, summaries, implementation, and fresh pytest runs)
- ASVS level: `1`
- Block-on policy: `high`

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-11-01-01 | T/I | mitigate | CLOSED | `backend/main.py:3098-3110` builds `explainability` directly from the returned result metadata (`matched_fields`, `matched_terms`, `source_memory_id`, fact lifecycle fields) instead of a parallel narrative layer; `tests/test_deep_user_memory_flows.py:47-72` proves the winner explanation stays aligned with the active fact and rerank signals. |
| T-11-01-02 | I | mitigate | CLOSED | `backend/main.py:3240-3277,3352-3357` keeps non-active long-term facts out of default search unless `include_history` or a non-active status is explicitly requested; `tests/test_deep_user_memory_flows.py:94-122,149-178` proves current-first behavior by default and history/conflict visibility only on explicit request. |
| T-11-02-01 | T/I | mitigate | CLOSED | `backend/governance/task_policy.py:44-133` classifies task kinds and blocks materialization for non-work/conversational content; `tests/test_task_governance_targets.py:28-82,190-269` covers system/meta/snapshot/work classification and `should_materialize_task(...)` boundaries. |
| T-11-02-02 | D | mitigate | CLOSED | `tests/test_deep_user_task_flows.py:113-191` drives `/tasks/normalize` through active noise archival, archived-noise pruning, and real-work survival assertions so over-aggressive cleanup fails visibly at public surfaces. |
| T-11-03-01 | I/E | mitigate | CLOSED | `backend/main.py:2659-2677,2006-2023` enforces project scope defaults, explicit multi-project selection, and metadata/filter conflict rejection; `tests/test_identity_e2e.py:28-147,150-210` proves single-project defaulting, explicit-scope requirements for multi-project keys, and scoped search/write behavior. |
| T-11-03-02 | I | mitigate | CLOSED | `backend/main.py:2680-2705` hides foreign task/memory resources behind `404` unless the caller is admin; `tests/test_identity_unit.py:57-117` verifies helper-level fail-closed behavior and admin bypass, while `tests/test_identity_e2e.py:213-330,365-416` proves the same behavior through fetch/close/archive/delete API routes. |
| T-11-04-01 | T/I | mitigate | CLOSED | `backend/main.py:1195-1233` encodes the approved scope evidence hierarchy: hard `project_id`/`task_id` wins, stable preference/project-index facts route to `user_global`, and ambiguity falls into `migration_review`; `tests/test_scope_model_unit.py:4-43` covers each branch directly. |
| T-11-04-02 | I | mitigate | CLOSED | `backend/main.py:1236-1256` keeps mixed-scope answer roles as a small deterministic intent table rather than open-ended heuristics; `tests/test_scope_model_unit.py:46-57` verifies the preference and task intent mappings. |

## Fresh Verification

- `uv run pytest tests/test_deep_user_memory_flows.py -x` -> `3 passed in 0.60s`
- `uv run pytest tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py -x` -> `16 passed in 0.84s`
- `uv run pytest tests/test_identity_e2e.py tests/test_identity_unit.py -x` -> `26 passed in 1.32s`
- `uv run pytest tests/test_scope_model_unit.py -x` -> `7 passed in 0.67s`

## Accepted Risks Log

None.

## Transfer Evidence

None.

## Unregistered Flags

None. No `## Threat Flags` section was present in:

- `11-01-SUMMARY.md`
- `11-02-SUMMARY.md`
- `11-03-SUMMARY.md`
- `11-04-SUMMARY.md`

## Audit Summary

- Closed threats: `8/8`
- Open threats: `0/8`
- Phase 11 is security-secured: the fail-closed project-scope matrix, history-gated retrieval behavior, noise-resistant task materialization, cleanup safety, and helper-level scope-model seams all have direct regression evidence in the shipped codebase.
