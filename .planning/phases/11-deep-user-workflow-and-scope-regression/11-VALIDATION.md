---
phase: 11
slug: deep-user-workflow-and-scope-regression
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-17
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.x |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_deep_user_memory_flows.py tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py tests/test_identity_unit.py tests/test_scope_model_unit.py -x` |
| **Full suite command** | `uv run pytest tests/test_deep_user_memory_flows.py tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py tests/test_identity_e2e.py tests/test_identity_unit.py tests/test_scope_model_unit.py -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_deep_user_memory_flows.py tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py tests/test_identity_unit.py tests/test_scope_model_unit.py -x`
- **After every plan wave:** Run `uv run pytest tests/test_deep_user_memory_flows.py tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py tests/test_identity_e2e.py tests/test_identity_unit.py tests/test_scope_model_unit.py -x`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | E2E-01 / E2E-02 | T-11-01-02 | Default retrieval stays current-first and only exposes superseded or conflict-review facts when history-aware retrieval is explicitly requested | integration | `uv run pytest tests/test_deep_user_memory_flows.py -x` | ✅ | green |
| 11-01-02 | 01 | 1 | E2E-01 | T-11-01-01 | Explanation assertions stay grounded in actual rerank and fact-lifecycle signals instead of a fabricated second ranking layer | integration | `uv run pytest tests/test_deep_user_memory_flows.py -x` | ✅ | green |
| 11-02-01 | 02 | 2 | E2E-03 | T-11-02-01 | Multi-hop task handoff preserves task identity, current state, and next action across public task and search surfaces | integration | `uv run pytest tests/test_deep_user_task_flows.py -x` | ✅ | green |
| 11-02-02 | 02 | 2 | E2E-03 | T-11-02-02 | Cleanup normalizes noise without deleting or hiding legitimate active work and its task memory | integration | `uv run pytest tests/test_deep_user_task_flows.py tests/test_task_governance_targets.py -x` | ✅ | green |
| 11-02-03 | 02 | 2 | UNIT-01 | T-11-02-01 | Task classification and materialization suppression fail locally for system, meta, snapshot, and non-work edges | unit | `uv run pytest tests/test_task_governance_targets.py -x` | ✅ | green |
| 11-03-01 | 03 | 3 | AUTH-01 / AUTH-02 | T-11-03-01 | Scoped keys must default correctly, require explicit project selection for multi-project access, and fail closed across memory and task routes | integration | `uv run pytest tests/test_identity_e2e.py -x` | ✅ | green |
| 11-03-02 | 03 | 3 | UNIT-02 | T-11-03-02 | Helper seams reject conflicting project scope and hide foreign resources behind endpoint-faithful 404 behavior | unit | `uv run pytest tests/test_identity_unit.py -x` | ✅ | green |
| 11-04-01 | 04 | 4 | UNIT-02 | T-11-04-01 / T-11-04-02 | Scope-model helper seams keep evidence-tier routing deterministic and mixed-retrieval answer roles intent-led without broad API drift | unit | `uv run pytest tests/test_scope_model_unit.py -x` | ✅ | green |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | -- | All Phase 11 target behaviors have automated pytest coverage across story-level and helper-level suites | None |

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-17
