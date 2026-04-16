---
phase: 10-test-harness-and-lane-foundation
plan: "04"
subsystem: testing
tags: [harness, fake-memory, runtime-drivers, payload-protocol, regression-hardening]
requires:
  - phase: 10-01
    provides: shared FakeMemory and live harness foundation
  - phase: 10-02
    provides: runtime driver coverage for scheduler and worker entrypoints
  - phase: 10-03
    provides: explicit fast/slow lane governance for the Phase 10 suites
provides:
  - sentinel-wrapped subprocess payload protocol for runtime drivers
  - faithful FakeMemory structured-content extraction with strict production-compatible contract
  - stable lock/idempotency defaults and env guards for runtime driver helpers
  - deferred milestone handoff for slow-lane DX and real mem0 contract parity
affects: [phase-11, phase-12, phase-13, testing, ci]
tech-stack:
  added: []
  patterns: [sentinel payload protocol, strict test double, env allowlist, stable helper defaults]
key-files:
  created: []
  modified:
    - tests/support/fake_memory.py
    - tests/test_support_fake_memory.py
    - tests/support/runtime_drivers.py
    - tests/test_runtime_driver_support.py
    - scripts/governance_worker.py
    - scripts/scheduled_consolidate.py
    - .planning/phases/10-test-harness-and-lane-foundation/deferred-items.md
key-decisions:
  - "Treat plan/research artifacts as versioned GSD execution inputs, but keep `.planning/config.json` and `.planning/codebase/` local-only."
  - "Runtime driver payload discovery now relies on explicit begin/end sentinels instead of reverse-scanning stdout for a JSON dict."
  - "FakeMemory should be strict enough to catch shape drift and typoed kwargs, but must still honor the real backend contract such as `search(..., filters=...)`."
patterns-established:
  - "Worker and scheduler scripts emit final JSON payloads inside sentinel markers so test helpers can ignore log noise and pretty-printed JSON safely."
  - "FakeMemory now models structured chat content, deep-copy boundaries, and metadata filtering closely enough for backend regression suites to trust it as a test double."
requirements-completed: [HARN-01, HARN-02, HARN-03]
duration: 1 session
completed: 2026-04-17
---

# Phase 10 Plan 04: Adversarial Review Hardening Summary

**Sentinel payload parsing, strict-but-compatible FakeMemory semantics, stable runtime-driver contracts, and explicit deferred follow-ups closed the ten adversarial gaps in the Phase 10 harness.**

## Performance

- **Duration:** 1 session
- **Started:** 2026-04-17
- **Completed:** 2026-04-17
- **Tasks:** 5
- **Files modified:** 7 tracked files plus planning tracking updates

## Accomplishments

- Replaced the runtime-driver "last JSON line wins" heuristic with an explicit sentinel payload protocol shared by `tests/support/runtime_drivers.py`, `scripts/governance_worker.py`, and `scripts/scheduled_consolidate.py`.
- Hardened `FakeMemory` so it extracts structured chat text faithfully, deep-copies returned records, raises `FakeMemoryNotFound` on missing ids, and supports the real backend's `search(..., filters=...)` contract instead of silently drifting from production behavior.
- Added stable lock/idempotency defaults, an env allowlist, and contract-key override guards to runtime drivers, then documented the two strategic leftovers in `deferred-items.md`.
- Updated `.gitignore` so Phase 10 PLAN/RESEARCH artifacts are versionable GSD inputs while `.planning/config.json` and `.planning/codebase/` remain local-only.

## Verification

- `uv run pytest tests/test_support_fake_memory.py tests/test_runtime_driver_support.py -q` -> `24 passed`
- `uv run pytest tests/test_backend_baseline.py tests/test_task_governance_targets.py -q` -> `82 passed`
- `uv run pytest -m slow tests/test_harness_foundation_live.py tests/test_runtime_entrypoints_live.py -q` -> `4 passed`
- `uv run pytest -m "not slow" -x` -> `151 passed, 6 deselected in 5.12s`
- `rg -n "===AUTOMEM_PAYLOAD_BEGIN===" tests/support/runtime_drivers.py scripts/governance_worker.py scripts/scheduled_consolidate.py` -> sentinel markers present in all required files
- `rg -n "2026-04-17" .planning/phases/10-test-harness-and-lane-foundation/deferred-items.md` -> both adversarial-review deferred follow-ups recorded

## Task Commits

Each task was committed atomically where execution had already progressed before this session resumed:

1. **Task 1: Replace reverse-scan payload discovery with an explicit sentinel protocol** — `de11fb4` (test), `cdd4548` (feat)
2. **Task 2: Make FakeMemory `_extract_text` faithful to structured chat content** — `83c9e2b` (test), implementation completed in the resumed Task 3 workstream
3. **Task 3: Harden FakeMemory Map safety and production-compatible kwargs** — completed in current working tree before final docs/tracking update
4. **Task 4: Stabilize runtime drivers lock, idempotency, env, and extra_env contract** — completed in current working tree before final docs/tracking update
5. **Task 5: Record deferred strategic items** — completed in current working tree before final docs/tracking update

## Files Created/Modified

- `tests/support/fake_memory.py` — strict FakeMemory contract with faithful structured-content extraction, deep-copy boundaries, `filters` support, injected clock/score hooks, and `FakeMemoryNotFound`.
- `tests/test_support_fake_memory.py` — regression tests for structured content, defensive copies, strict kwargs, injected clock/score, not-found behavior, and `filters` support.
- `tests/support/runtime_drivers.py` — sentinel parsing, stable lock/idempotency defaults, env allowlist, protected contract keys, and UTF-8 subprocess encoding.
- `tests/test_runtime_driver_support.py` — sentinel protocol coverage, stable-default coverage, contract-override protection, and env allowlist regression tests.
- `scripts/governance_worker.py`, `scripts/scheduled_consolidate.py` — sentinel-wrapped final payload emission for worker and scheduler runtime entrypoints.
- `.planning/phases/10-test-harness-and-lane-foundation/deferred-items.md` — explicit Phase 13 and v2 follow-ups for the two strategic items intentionally not fixed in Phase 10.

## Decisions Made

- The strict FakeMemory contract should model only the kwargs the real backend actually uses, which includes `filters` on `search`; rejecting `filters` was too strict and broke backend regression coverage.
- The runtime-driver env should start from a minimal allowlist so developer-specific shell variables cannot change slow-lane behavior silently.
- PLAN and RESEARCH artifacts are part of the reproducible GSD execution chain and should be versionable; generated codebase maps and local config remain local.

## Deviations from Plan

### Auto-fixed Issues

**1. FakeMemory strictness initially overshot the real backend contract**
- **Found during:** Task 3 regression verification on `tests/test_backend_baseline.py`
- **Issue:** `FakeMemory.search()` rejected the `filters` kwarg even though `backend/main.py:3162-3169` passes `filters` during hybrid search.
- **Fix:** Added a focused failing test and implemented metadata-based filter matching in `FakeMemory.search()` while keeping unknown kwargs strict.
- **Files modified:** `tests/support/fake_memory.py`, `tests/test_support_fake_memory.py`
- **Verification:** `uv run pytest tests/test_backend_baseline.py tests/test_task_governance_targets.py -q`

---

**Total deviations:** 1 auto-fixed
**Impact on plan:** Improved fidelity — the test double now matches the production-facing contract instead of enforcing an artificial subset.

## Issues Encountered

- The repository had already partially progressed through 10-04 before this session resumed: Task 1 and part of Task 2 were present in history, while Task 3 existed as uncommitted local work. I preserved that work, validated it against the actual backend contract, and resumed from there instead of resetting the tree.

## User Setup Required

None.

## Next Phase Readiness

- Phase 10 is now closed with explicit harness hardening on top of the original foundation.
- Phase 11 can plan deep-user workflow coverage on a stricter and more trustworthy test substrate.
- Phase 13 and v2 have explicit deferred entries for the two remaining strategic testing investments.

## Self-Check: PASSED
