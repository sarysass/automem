---
phase: 10-test-harness-and-lane-foundation
plan: "03"
subsystem: testing
tags: [pytest, coverage, ci, documentation]
requires:
  - phase: 10-01
    provides: shared live backend harness and fake-memory test support
  - phase: 10-02
    provides: runtime-driver coverage for scheduler and worker entrypoints
provides:
  - explicit fast and slow pytest lanes for Phase 10
  - strict marker registration with subprocess-aware coverage config
  - contributor and CI commands aligned to the fast default lane
affects: [phase-11, phase-12, ci, contributor-workflow]
tech-stack:
  added: []
  patterns: [strict pytest markers, fast-slow lane governance, relative planning links]
key-files:
  created: [tests/test_lane_selection.py]
  modified: [pyproject.toml, CONTRIBUTING.md, .github/workflows/ci.yml, .planning/PROJECT.md, .planning/research/SUMMARY.md, .planning/phases/10-test-harness-and-lane-foundation/deferred-items.md, .planning/phases/10-test-harness-and-lane-foundation/10-02-SUMMARY.md]
key-decisions:
  - "Keep the default PR/test loop on `uv run pytest -m \"not slow\"` and make the live harness lane explicit by name."
  - "Sanitize private paths from committed artifacts instead of weakening repository layout enforcement when the fast lane failed."
patterns-established:
  - "Lane selection is guarded by `tests/test_lane_selection.py`, which parses `pyproject.toml` and the Phase 10 validation contract."
  - "Planning docs should use relative repo links or generic home-path references so repository-layout scans stay green."
requirements-completed: [HARN-03]
duration: 5min
completed: 2026-04-17
---

# Phase 10 Plan 03: Fast And Slow Lane Governance Summary

**Strict pytest lane governance with executable lane-selection checks, contributor/CI fast-lane commands, and a restored runnable default lane**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-16T16:42:28Z
- **Completed:** 2026-04-16T16:48:23Z
- **Tasks:** 2
- **Files modified:** 8 tracked files, plus 2 ignored local artifacts sanitized for verification

## Accomplishments

- Added `tests/test_lane_selection.py` and updated `pyproject.toml` so pytest now enforces strict `slow` and `serial` markers, plus subprocess-aware coverage for live-process suites.
- Published exact fast and slow lane commands in `CONTRIBUTING.md` and kept the default Python CI job on `uv run pytest -m "not slow"`.
- Removed private absolute-path references from tracked planning artifacts and sanitized matching ignored local files so the default fast lane now passes instead of failing in repository-layout checks.

## Verification

- `uv run pytest tests/test_lane_selection.py -x` -> `3 passed in 0.00s`
- `uv run pytest -m "not slow" -x` -> `129 passed, 6 deselected in 5.36s`
- `uv run pytest -m slow tests/test_harness_foundation_live.py tests/test_runtime_entrypoints_live.py -x` -> `4 passed in 2.99s`

## Task Commits

Each task was committed atomically:

1. **Task 1: Register strict fast and slow lane config with an executable lane-selection test** - `39b4eec` (test), `80c6635` (feat)
2. **Task 2: Publish fast and slow lane commands in contributor docs and keep PR CI on the fast lane** - `504ef55` (chore)
3. **Verification deviation fix: remove private paths from tracked artifacts** - `224f46a` (fix)

**Plan metadata:** pending final docs commit at completion time

## Files Created/Modified

- `tests/test_lane_selection.py` - Parses `pyproject.toml`, checks Phase 10 live-suite markers, and locks the lane-command contract to the validation artifact.
- `pyproject.toml` - Registers strict pytest markers and coverage subprocess patching for child-process live tests.
- `CONTRIBUTING.md` - Documents fast and slow pytest lanes in Chinese-first contributor guidance.
- `.github/workflows/ci.yml` - Keeps the default Python CI job on the fast lane.
- `.planning/PROJECT.md`, `.planning/research/SUMMARY.md`, `.planning/phases/10-test-harness-and-lane-foundation/deferred-items.md`, `.planning/phases/10-test-harness-and-lane-foundation/10-02-SUMMARY.md` - Replace absolute private paths with relative or generic wording so repository-layout checks pass.

## Decisions Made

- Kept the fast lane as the default contributor and PR path, while making the slow lane an explicit targeted command for the two Phase 10 live suites.
- Fixed the private-path regression by sanitizing artifacts instead of loosening `tests/test_repository_layout.py`, preserving the repo’s privacy guardrail.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Sanitized private-path references that broke the default fast lane**
- **Found during:** Plan-level verification after Task 2
- **Issue:** `uv run pytest -m "not slow"` failed in `tests/test_repository_layout.py::test_repository_has_no_legacy_product_names_or_private_paths` because tracked planning docs and ignored local artifacts still contained absolute home-directory paths.
- **Fix:** Replaced tracked absolute repo links with relative links or generic wording, and sanitized matching ignored local files (`.claude/settings.local.json`, `.planning/phases/10-test-harness-and-lane-foundation/10-RESEARCH.md`) in the working tree so the repository scan no longer finds private paths.
- **Files modified:** `.planning/PROJECT.md`, `.planning/research/SUMMARY.md`, `.planning/phases/10-test-harness-and-lane-foundation/deferred-items.md`, `.planning/phases/10-test-harness-and-lane-foundation/10-02-SUMMARY.md`, plus ignored local `.claude/settings.local.json` and `.planning/phases/10-test-harness-and-lane-foundation/10-RESEARCH.md`
- **Verification:** A repo-wide privacy-pattern scan returned no matches after the cleanup, and the fast lane then passed with `129 passed, 6 deselected`.
- **Committed in:** `224f46a` for tracked artifacts; ignored local sanitization remained uncommitted by design

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to satisfy the plan’s requirement that the documented fast lane be genuinely runnable. The fix stayed narrow and preserved the repository-layout safety check.

## Issues Encountered

- `git add` refused ignored local files involved in the fast-lane failure. I kept the commit limited to tracked artifacts and left the ignored-file sanitization in the working tree, which is enough for the local fast lane and avoids broadening repo tracking scope.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 10 now has explicit fast and slow test lanes, an executable lane-selection guard, and a passing default fast lane.
- Phase 11 can build deep-user workflow scenarios on top of the documented fast lane without re-solving CI/test-governance basics.

## Self-Check: PASSED
