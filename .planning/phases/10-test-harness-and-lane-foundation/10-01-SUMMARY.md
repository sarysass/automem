---
phase: 10-test-harness-and-lane-foundation
plan: "01"
subsystem: testing
tags: [pytest, fastapi, uvicorn, httpx, sqlite, harness]
requires:
  - phase: 09-milestone-validation-baseline
    provides: Verified backend/auth contracts and the v1.1 validation map this harness reuses
provides:
  - Shared FakeMemory support module for fast and slow regression lanes
  - Reusable child-process live backend harness with temp SQLite and lock-file isolation
  - Condition-based HTTP readiness helper and executable `/healthz` auth proof
affects: [10-02, 10-03, phase-11]
tech-stack:
  added: []
  patterns: [dynamic backend import with fake-memory injection, condition-based HTTP readiness polling]
key-files:
  created:
    - tests/__init__.py
    - tests/support/__init__.py
    - tests/support/fake_memory.py
    - tests/support/live_backend.py
    - tests/support/waiting.py
    - tests/test_support_fake_memory.py
    - tests/test_harness_foundation_live.py
  modified:
    - tests/conftest.py
key-decisions:
  - "The live harness boots backend/main.py in a child process and injects FakeMemory before serving requests."
  - "All harness polling lives in tests/support/waiting.py so live suites do not scatter raw sleeps."
patterns-established:
  - "Shared test dependencies live under tests/support and are imported by both fast and slow lanes."
  - "Live backend tests prove auth over real HTTP against /healthz instead of bypassing verify_api_key."
requirements-completed: [HARN-01]
duration: 8m
completed: 2026-04-17
---

# Phase 10 Plan 01: Shared Harness Foundation Summary

**Shared FakeMemory support plus a real HTTP live-backend harness that proves `/healthz` auth against isolated temp SQLite state**

## Performance

- **Duration:** 8m
- **Started:** 2026-04-17T00:12:31+08:00
- **Completed:** 2026-04-17T00:20:31+08:00
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Extracted the inline `FakeMemory` test double into `tests/support/fake_memory.py` and rewired `tests/conftest.py` to import it without changing fast-lane bootstrap values.
- Added `tests/support/live_backend.py` as a reusable child-process harness that boots the real FastAPI app over HTTP with temp `tasks.db`, `history.db`, worker lock, and consolidate lock paths.
- Added `tests/support/waiting.py` and `tests/test_harness_foundation_live.py` so the repo now has an executable HARN-01 proof for fail-closed `/healthz` auth and temp-path runtime state.

## Task Commits

1. **Task 1 RED: shared fake memory support** - `8a60e46` (`test`)
2. **Task 1 GREEN: extract shared fake memory support** - `b8081da` (`feat`)
3. **Task 2 RED: live backend harness proof** - `0ba4316` (`test`)
4. **Task 2 GREEN: live backend harness primitives** - `933e2c8` (`feat`)

## Files Created/Modified

- `tests/support/fake_memory.py` - shared deterministic fake backend for fast and slow suites
- `tests/conftest.py` - imports the extracted fake backend while preserving the existing temp-env bootstrap
- `tests/support/live_backend.py` - child-process HTTP harness that injects `FakeMemory` before serving requests
- `tests/support/waiting.py` - condition-based readiness polling helper used by live suites
- `tests/test_support_fake_memory.py` - RED/GREEN contract test for the extracted fake backend
- `tests/test_harness_foundation_live.py` - slow/serial live proof for `/healthz` auth and temp runtime paths

## Decisions Made

- Kept the live harness in test code and booted `backend/main.py` through a dynamic import so no production-only endpoints or flags were added.
- Exposed reusable harness state as a dataclass (`base_url`, temp db paths, lock paths, auth headers) so follow-on worker/scheduler plans can reuse the same foundation.
- Left `slow` and `serial` as unregistered markers for now because plan `10-03` owns pytest lane registration and command wiring.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added a minimal `tests/__init__.py` package marker**
- **Found during:** Task 1 (Extract the shared deterministic fake backend without changing fast-lane behavior)
- **Issue:** Importing `tests.support.fake_memory` failed because the repo’s `tests/` directory was not importable as a package from pytest and spawned subprocesses.
- **Fix:** Added `tests/__init__.py` so the new shared support modules resolve consistently from both the main pytest process and the live child-process harness.
- **Files modified:** `tests/__init__.py`
- **Verification:** `uv run pytest tests/test_support_fake_memory.py -x`
- **Committed in:** `b8081da`

---

**Total deviations:** 1 auto-fixed (1 blocking issue)
**Impact on plan:** Low. The package marker was required to make the planned `tests.support.*` structure importable and did not change product behavior.

## Issues Encountered

- `uv run pytest -m slow tests/test_harness_foundation_live.py -x` emits two `PytestUnknownMarkWarning` warnings for `slow` and `serial`. This is expected until plan `10-03` registers the lane markers in pytest config.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan `10-02` can reuse `tests/support/live_backend.py` and the temp-path env contract to drive the real worker and scheduler scripts.
- Plan `10-03` should register the `slow` and `serial` markers so the new harness proof no longer warns during slow-lane runs.

## Self-Check: PASSED

- Verified the summary and all created harness files exist on disk.
- Verified task commits `8a60e46`, `b8081da`, `0ba4316`, and `933e2c8` exist in git history.
