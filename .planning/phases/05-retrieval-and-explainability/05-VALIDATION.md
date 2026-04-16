---
phase: 05
slug: retrieval-and-explainability
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
updated: 2026-04-16
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `./.venv/bin/pytest tests/test_backend_baseline.py tests/test_identity_unit.py tests/test_identity_e2e.py tests/test_cli_memory.py` |
| **Full suite command** | `./.venv/bin/pytest tests/test_backend_baseline.py tests/test_identity_unit.py tests/test_identity_e2e.py tests/test_cli_memory.py` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run the retrieval and explainability regression command
- **After every plan wave:** Re-run the retrieval and explainability regression command
- **Before `$gsd-verify-work`:** The retrieval and explainability regression command must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | RET-01, RET-02 | — | Search combines semantic, lexical, and metadata recall paths and returns structured explainability for each result | integration | `./.venv/bin/pytest tests/test_backend_baseline.py tests/test_identity_unit.py tests/test_identity_e2e.py tests/test_cli_memory.py` | ✅ | ✅ green |

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
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-16
