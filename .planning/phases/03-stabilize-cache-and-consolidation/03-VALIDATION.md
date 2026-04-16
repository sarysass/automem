---
phase: 03
slug: stabilize-cache-and-consolidation
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
updated: 2026-04-16
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_consolidate_respects_requested_user_scope tests/test_backend_baseline.py::test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise tests/test_backend_baseline.py::test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks tests/test_backend_baseline.py::test_task_normalize_archives_non_work_items_and_rewrites_titles tests/test_backend_baseline.py::test_cache_rebuild_restores_index_for_existing_memories tests/test_backend_baseline.py::test_cache_rebuild_removes_stale_entries tests/test_scheduled_consolidate.py::test_run_consolidation_retries_before_success tests/test_scheduled_consolidate.py::test_main_skips_when_lock_exists` |
| **Full suite command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_consolidate_respects_requested_user_scope tests/test_backend_baseline.py::test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise tests/test_backend_baseline.py::test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks tests/test_backend_baseline.py::test_task_normalize_archives_non_work_items_and_rewrites_titles tests/test_backend_baseline.py::test_cache_rebuild_restores_index_for_existing_memories tests/test_backend_baseline.py::test_cache_rebuild_removes_stale_entries tests/test_scheduled_consolidate.py::test_run_consolidation_retries_before_success tests/test_scheduled_consolidate.py::test_main_skips_when_lock_exists` |
| **Estimated runtime** | ~1 second |

---

## Sampling Rate

- **After every task commit:** Run the cache and consolidation regression command
- **After every plan wave:** Re-run the same cache and consolidation regression command
- **Before `$gsd-verify-work`:** The cache and consolidation regression command must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | CONS-01, CONS-02 | — | Maintenance paths rebuild cache before normalization/consolidation and use safe replacement-first canonical rewrites guarded by scheduler lock and retry behavior | integration | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_consolidate_respects_requested_user_scope tests/test_backend_baseline.py::test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise tests/test_backend_baseline.py::test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks tests/test_backend_baseline.py::test_task_normalize_archives_non_work_items_and_rewrites_titles tests/test_backend_baseline.py::test_cache_rebuild_restores_index_for_existing_memories tests/test_backend_baseline.py::test_cache_rebuild_removes_stale_entries tests/test_scheduled_consolidate.py::test_run_consolidation_retries_before_success tests/test_scheduled_consolidate.py::test_main_skips_when_lock_exists` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-16
