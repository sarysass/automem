---
phase: 10-test-harness-and-lane-foundation
plan: "02"
subsystem: testing
tags: [pytest, httpx, uv, governance, harness]
requires:
  - phase: 10-test-harness-and-lane-foundation
    provides: Live backend harness with temp state, fake-memory injection, and polling helpers from 10-01
provides:
  - Runtime subprocess drivers for `scripts/scheduled_consolidate.py` and `scripts/governance_worker.py`
  - Slow-lane live coverage for scheduler enqueue and worker run-next flows through public HTTP endpoints
  - HARN-02 proof that real runtime entrypoints interoperate with the shared harness without inline backend seams
affects: [phase-11, phase-12, phase-13, runtime-regression-lanes]
tech-stack:
  added: []
  patterns:
    - subprocess-driven runtime testing via `uv run python ...`
    - public-surface polling with `wait_for_condition`
    - temp lock/idempotency env isolation for worker and scheduler scripts
key-files:
  created:
    - tests/support/runtime_drivers.py
    - tests/test_runtime_drivers.py
    - tests/test_runtime_entrypoints_live.py
  modified: []
key-decisions:
  - "Runtime driver helpers execute committed scripts as subprocesses and parse stdout JSON instead of importing script entrypoints into tests."
  - "Live runtime proof seeds data through `/memories` but observes queue progression only through `/governance/jobs`, `/metrics`, and `/audit-log`."
patterns-established:
  - "Runtime driver result pattern: return command, env overrides, exit code, stdout/stderr, and parsed payload for assertion-friendly failures."
  - "Slow live orchestration tests should wait on public HTTP state transitions instead of sleeping in the test body."
requirements-completed: [HARN-02]
duration: 7m
completed: 2026-04-17
---

# Phase 10 Plan 02: Runtime Entrypoints Summary

**Real scheduler and worker scripts now run against the shared live harness, with slow pytest coverage proving enqueue, run-next, metrics, and audit behavior over HTTP.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-17T00:27:56+08:00
- **Completed:** 2026-04-17T00:34:41+08:00
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added reusable subprocess wrappers that launch `scripts/scheduled_consolidate.py` and `scripts/governance_worker.py` through `uv run python` with isolated harness env.
- Added slow live driver coverage that proves the subprocess helpers return parsed enqueue and run-next payloads.
- Added the HARN-02 proof suite that seeds duplicate long-term memory through the live API, then validates queue state, metrics, and audit evidence through public endpoints only.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add subprocess runtime drivers for the real worker and scheduler scripts** - `c25d35b` (test), `076a848` (feat)
2. **Task 2: Prove scheduler enqueue and worker run-next flows through the live harness** - `941be9a` (test)

## Files Created/Modified
- `tests/support/runtime_drivers.py` - Runs the committed scheduler and worker scripts in subprocesses with temp harness env and parsed JSON results.
- `tests/test_runtime_drivers.py` - Slow live driver contract tests for scheduler enqueue and worker run-next payloads.
- `tests/test_runtime_entrypoints_live.py` - Slow end-to-end HARN-02 proof over `/memories`, `/governance/jobs`, `/metrics`, and `/audit-log`.

## Decisions Made
- Kept runtime verification at the real script boundary by calling `uv run python scripts/...` instead of importing `main()` functions.
- Used unique temp lock files and idempotency keys per subprocess invocation so scheduler and worker runs stay deterministic inside each harness temp dir.
- Seeded duplicate long-term memories through `/memories` so worker completion asserts meaningful consolidation effects (`duplicate_long_term_count >= 1`) rather than an empty no-op job.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `uv run pytest -m "not slow"` still fails in `tests/test_repository_layout.py::test_repository_has_no_legacy_product_names_or_private_paths` because pre-existing files (`.claude/settings.local.json` and existing phase docs) contain absolute local home-directory paths. Logged to `.planning/phases/10-test-harness-and-lane-foundation/deferred-items.md` and left out of scope for HARN-02.
- `pytest` warns that `slow` and `serial` markers are not registered yet. This is expected before Plan `10-03`, which owns lane registration.
- The Task 2 live proof passed immediately once written because Task 1 plus Phase 10-01 already supplied the needed runtime behavior. The task therefore landed as executable proof coverage rather than requiring an extra implementation commit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 10 now has both HARN-01 and HARN-02 covered with a shared live harness plus real runtime subprocesses.
- Plan `10-03` can now register `slow` and `serial` markers in pytest/CI/docs without needing more worker or scheduler harness plumbing.
- The unrelated repository-layout assertion failure remains deferred and should be handled separately from lane registration.

## Self-Check: PASSED
