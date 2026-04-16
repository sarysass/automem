---
phase: 01
slug: auth-defaults-and-tenant-isolation
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
updated: 2026-04-16
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_missing_api_key_requires_header tests/test_backend_baseline.py::test_invalid_api_key_is_rejected tests/test_backend_baseline.py::test_agent_keys_reject_non_admin_without_user_binding tests/test_backend_baseline.py::test_unbound_non_admin_api_key_is_rejected_at_verification tests/test_backend_baseline.py::test_agent_key_enforces_bound_agent_identity` |
| **Full suite command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_missing_api_key_requires_header tests/test_backend_baseline.py::test_invalid_api_key_is_rejected tests/test_backend_baseline.py::test_agent_keys_reject_non_admin_without_user_binding tests/test_backend_baseline.py::test_unbound_non_admin_api_key_is_rejected_at_verification tests/test_backend_baseline.py::test_agent_key_enforces_bound_agent_identity` |
| **Estimated runtime** | ~1 second |

---

## Sampling Rate

- **After every task commit:** Run the quick auth regression command
- **After every plan wave:** Re-run the full auth regression command
- **Before `$gsd-verify-work`:** The auth regression command must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | AUTH-01, AUTH-02 | — | Missing or invalid API keys are rejected, and non-admin keys cannot exist or operate without a bound `user_id` | integration | `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_missing_api_key_requires_header tests/test_backend_baseline.py::test_invalid_api_key_is_rejected tests/test_backend_baseline.py::test_agent_keys_reject_non_admin_without_user_binding tests/test_backend_baseline.py::test_unbound_non_admin_api_key_is_rejected_at_verification tests/test_backend_baseline.py::test_agent_key_enforces_bound_agent_identity` | ✅ | ✅ green |

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
