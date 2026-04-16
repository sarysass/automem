---
phase: 07
slug: runtime-architecture-upgrade
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
updated: 2026-04-16
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py tests/test_scheduled_consolidate.py tests/test_governance_worker.py` |
| **Full suite command** | `./.venv/bin/python -m pytest` |
| **Estimated runtime** | ~7 seconds |

---

## Sampling Rate

- **After every task commit:** Run the runtime and governance worker regression command
- **After every plan wave:** Re-run `./.venv/bin/python -m pytest`
- **Before `$gsd-verify-work`:** The runtime regression command and the full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | OPS-01, OPS-02 | — | Governance work is split between hot-path API and background worker, and runtime topology exposes the API/worker/MCP contract with queue observability | integration | `./.venv/bin/python -m pytest tests/test_backend_baseline.py tests/test_scheduled_consolidate.py tests/test_governance_worker.py` | ✅ | ✅ green |

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
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-16
