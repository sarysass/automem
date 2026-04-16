---
phase: 09
slug: milestone-validation-baseline
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
updated: 2026-04-16
---

# Phase 09 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py tests/test_identity_unit.py tests/test_identity_e2e.py tests/test_cli_memory.py tests/test_scheduled_consolidate.py tests/test_governance_worker.py` |
| **Full suite command** | `./.venv/bin/python -m pytest` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run the phase-group command mapped below for the affected plan
- **After every plan wave:** Run `./.venv/bin/python -m pytest`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | AUTH-01, AUTH-02, GOV-01, CONS-01, CONS-02 | T09-01 / T09-02 | Foundational VALIDATION files only claim evidence already proven by auth, governance, and consolidation regressions | integration | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_missing_api_key_requires_header tests/test_backend_baseline.py::test_invalid_api_key_is_rejected tests/test_backend_baseline.py::test_agent_keys_reject_non_admin_without_user_binding tests/test_backend_baseline.py::test_unbound_non_admin_api_key_is_rejected_at_verification tests/test_backend_baseline.py::test_agent_key_enforces_bound_agent_identity tests/test_backend_baseline.py::test_add_memory_rejects_task_noise_markers tests/test_backend_baseline.py::test_add_memory_rejects_transport_metadata_noise tests/test_backend_baseline.py::test_memory_route_drops_time_scaffold tests/test_backend_baseline.py::test_memory_route_does_not_materialize_task_rows tests/test_backend_baseline.py::test_consolidate_respects_requested_user_scope tests/test_backend_baseline.py::test_consolidate_canonicalizes_legacy_preferences_and_removes_task_noise tests/test_backend_baseline.py::test_consolidate_removes_time_and_metadata_noise_and_normalizes_tasks tests/test_backend_baseline.py::test_task_normalize_archives_non_work_items_and_rewrites_titles tests/test_backend_baseline.py::test_cache_rebuild_restores_index_for_existing_memories tests/test_backend_baseline.py::test_cache_rebuild_removes_stale_entries tests/test_scheduled_consolidate.py::test_run_consolidation_retries_before_success tests/test_scheduled_consolidate.py::test_main_skips_when_lock_exists tests/test_adapter_regressions.py::test_claude_capture_commits_duplicate_state_only_after_success` | ✅ | ✅ green |
| 09-02-01 | 02 | 1 | IAM-01, IAM-02, RET-01, RET-02 | T09-03 / T09-04 | Identity and retrieval VALIDATION files must reuse existing project-scope and hybrid-recall regression evidence | integration | `./.venv/bin/pytest tests/test_backend_baseline.py tests/test_identity_unit.py tests/test_identity_e2e.py tests/test_cli_memory.py` | ✅ | ✅ green |
| 09-03-01 | 03 | 1 | FACT-01, FACT-02, OPS-01, OPS-02 | T09-05 / T09-06 | Fact lifecycle and runtime VALIDATION files must reuse existing lifecycle and governance-worker regression evidence | integration | `./.venv/bin/python -m pytest tests/test_backend_baseline.py -k 'supersedes_previous_active_fact or conflict_review_keeps_existing_active_fact or consolidate_supersedes_legacy_active_fact_versions' && ./.venv/bin/python -m pytest tests/test_backend_baseline.py tests/test_scheduled_consolidate.py tests/test_governance_worker.py` | ✅ | ✅ green |
| 09-04-01 | 04 | 2 | AUTH-01, AUTH-02, GOV-01, CONS-01, CONS-02, IAM-01, IAM-02, RET-01, RET-02, FACT-01, FACT-02, OPS-01, OPS-02 | T09-07 / T09-08 | Milestone audit must derive Nyquist state from actual 01-07 VALIDATION artifacts rather than a stale missing list | docs | `python - <<'PY'\nfrom pathlib import Path\nimport re\nphase_files = {\n    '01': Path('.planning/phases/01-auth-defaults-and-tenant-isolation/01-VALIDATION.md'),\n    '02': Path('.planning/phases/02-centralize-memory-governance/02-VALIDATION.md'),\n    '03': Path('.planning/phases/03-stabilize-cache-and-consolidation/03-VALIDATION.md'),\n    '04': Path('.planning/phases/04-shared-identity-and-access-model/04-VALIDATION.md'),\n    '05': Path('.planning/phases/05-retrieval-and-explainability/05-VALIDATION.md'),\n    '06': Path('.planning/phases/06-temporal-facts-and-conflict-governance/06-VALIDATION.md'),\n    '07': Path('.planning/phases/07-runtime-architecture-upgrade/07-VALIDATION.md'),\n}\nexpected = {'compliant': set(), 'partial': set(), 'missing': set()}\nfor phase, path in phase_files.items():\n    if not path.exists():\n        expected['missing'].add(phase)\n        continue\n    text = path.read_text()\n    nyquist_true = bool(re.search(r'^nyquist_compliant:\\s*true\\b', text, re.M))\n    task_rows = [line for line in text.splitlines() if re.match(r'^\\|\\s*\\d{2}-', line)]\n    has_non_green = any('| ✅ green |' not in line for line in task_rows)\n    if nyquist_true and not has_non_green:\n        expected['compliant'].add(phase)\n    else:\n        expected['partial'].add(phase)\naudit = Path('.planning/v1.0-MILESTONE-AUDIT.md').read_text()\ndef parse(name):\n    m = re.search(rf'{name}:\\s*\\[(.*?)\\]', audit, re.S)\n    if not m:\n        return set()\n    return {part.strip().strip(\"\\\"'\") for part in m.group(1).split(',') if part.strip()}\nactual = {\n    'compliant': parse('compliant_phases'),\n    'partial': parse('partial_phases'),\n    'missing': parse('missing_phases'),\n}\nassert actual == expected, f'audit nyquist mismatch: expected={expected}, actual={actual}'\nprint('nyquist coverage derived from phase validation artifacts')\nPY` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

All Phase 09 behaviors should be automatable through file assertions and existing pytest commands. If execution discovers a truly manual-only gap, record it during execution and keep `nyquist_compliant: false` until the exception is explicit.

---

## Validation Sign-Off

- [x] All tasks have automated verify or an explicit documented exception
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing infrastructure references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-16
