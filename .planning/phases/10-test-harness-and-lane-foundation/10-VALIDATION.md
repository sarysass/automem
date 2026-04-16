---
phase: 10
slug: test-harness-and-lane-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.x |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -m "not slow"` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~45 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m "not slow"`
- **After every plan wave:** Run `uv run pytest -m slow tests/test_harness_foundation_live.py tests/test_runtime_entrypoints_live.py`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | HARN-01 | T-10-01-01 / T-10-01-02 | Live backend boots with temp state, deterministic fake backend, and real FastAPI lifespan | integration | `uv run pytest -m slow tests/test_harness_foundation_live.py -x` | ❌ W0 | pending |
| 10-02-01 | 02 | 2 | HARN-02 | T-10-02-01 / T-10-02-02 | Scheduler enqueue and worker run-next flows operate through public runtime entrypoints only | integration | `uv run pytest -m slow tests/test_runtime_entrypoints_live.py -x` | ❌ W0 | pending |
| 10-03-01 | 03 | 3 | HARN-03 | T-10-03-01 / T-10-03-02 | Fast and slow lanes are selectable without leaking state across suites | integration/config | `uv run pytest tests/test_lane_selection.py -x` | ❌ W0 | pending |
| 10-04-01 | 04 | 4 | HARN-02 | T-10-04-01 | Runtime driver payload is extracted via an explicit sentinel protocol that survives log noise and pretty-printing | integration | `uv run pytest tests/test_runtime_driver_support.py tests/test_runtime_entrypoints_live.py -x` | ❌ W0 | pending |
| 10-04-02 | 04 | 4 | HARN-01 | T-10-04-02 | FakeMemory faithfully extracts structured chat content and refuses unknown message shapes | unit | `uv run pytest tests/test_support_fake_memory.py tests/test_harness_foundation_live.py -x` | ❌ W0 | pending |
| 10-04-03 | 04 | 4 | HARN-01 | T-10-04-03 / T-10-04-04 | FakeMemory returns defensive copies, rejects unknown kwargs, and exposes clock/score injection | unit | `uv run pytest tests/test_support_fake_memory.py tests/test_backend_baseline.py -x` | ❌ W0 | pending |
| 10-04-04 | 04 | 4 | HARN-02 | T-10-04-05 / T-10-04-06 / T-10-04-07 | Runtime driver helpers have stable lock/idempotency defaults, a guarded extra_env contract, and a minimal env allowlist | integration | `uv run pytest tests/test_runtime_driver_support.py tests/test_runtime_entrypoints_live.py -x` | ❌ W0 | pending |
| 10-04-05 | 04 | 4 | HARN-03 | n/a | Two strategic items are recorded in `deferred-items.md` with dated rationale | docs | `rg -n "2026-04-17" .planning/phases/10-test-harness-and-lane-foundation/deferred-items.md` | ❌ W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/support/fake_memory.py` — shared deterministic backend for fast and slow lanes
- [ ] `tests/support/live_backend.py` — child-process backend harness and env bootstrap
- [ ] `tests/support/runtime_drivers.py` — subprocess wrappers for scheduler and worker scripts
- [ ] `tests/support/waiting.py` — condition-based polling helpers for readiness and job state
- [ ] `tests/test_harness_foundation_live.py` — HARN-01 live harness verification
- [ ] `tests/test_runtime_entrypoints_live.py` — HARN-02 runtime entrypoint verification
- [ ] `tests/test_lane_selection.py` — HARN-03 lane selection verification
- [ ] `pyproject.toml` — strict markers and subprocess coverage configuration

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | -- | All Phase 10 target behaviors should be automatable through pytest and subprocess-driven runtime checks | None |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all missing references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
