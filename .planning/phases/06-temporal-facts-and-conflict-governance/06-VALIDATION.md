---
phase: 06
slug: temporal-facts-and-conflict-governance
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-16
updated: 2026-04-16
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `./.venv/bin/python -m pytest tests/test_backend_baseline.py -k 'supersedes_previous_active_fact or conflict_review_keeps_existing_active_fact or consolidate_supersedes_legacy_active_fact_versions'` |
| **Full suite command** | `./.venv/bin/python -m pytest` |
| **Estimated runtime** | ~6 seconds |

---

## Sampling Rate

- **After every task commit:** Run the targeted fact lifecycle regression command
- **After every plan wave:** Re-run `./.venv/bin/python -m pytest`
- **Before `$gsd-verify-work`:** Both the targeted command and the full suite must remain green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | FACT-01, FACT-02 | — | Long-term memory tracks lifecycle metadata, supersede chains, and explicit conflict-review state without flattening durable facts into plain text | integration | `./.venv/bin/python -m pytest tests/test_backend_baseline.py -k 'supersedes_previous_active_fact or conflict_review_keeps_existing_active_fact or consolidate_supersedes_legacy_active_fact_versions'` | ✅ | ✅ green |

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
