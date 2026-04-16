---
phase: 06-temporal-facts-and-conflict-governance
plan: 01
subsystem: api
tags: [long-term-memory, temporal-facts, conflict-governance, search, consolidate, fastapi, testing]
requires:
  - phase: 04-shared-identity-and-access-model
    provides: project-scoped identity enforcement and shared access boundaries
  - phase: 05-retrieval-and-explainability
    provides: explainable search payloads and hybrid cache-backed retrieval
provides:
  - fact lifecycle metadata on long-term memories
  - auto-supersede for replaceable fact slots
  - conflict-review states for ambiguous durable fact updates
  - history-aware search and legacy fact-chain repair in consolidate
affects: [runtime-architecture, adapters, search]
tech-stack:
  added: []
  patterns: [fact slots, lifecycle metadata, history filtering, cache-backed fact-chain repair]
key-files:
  created: [.planning/phases/06-temporal-facts-and-conflict-governance/06-VERIFICATION.md]
  modified: [backend/main.py, tests/test_backend_baseline.py, adapters/codex/mcp_server.py]
key-decisions:
  - "Replaceable fact slots such as language preference and user identity auto-supersede older active facts, while higher-risk slots fall into explicit conflict review."
  - "Historical facts stay queryable as first-class memory rows, but default search hides non-active long-term states unless history is requested."
patterns-established:
  - "Long-term writes normalize into fact metadata before persistence so search, audit, and consolidation all share the same lifecycle semantics."
  - "Consolidate now repairs legacy active fact chains by archiving stale versions as superseded history instead of only text-deduping."
requirements-completed: [FACT-01, FACT-02]
duration: 1 session
completed: 2026-04-16
---

# Phase 06: Temporal Facts And Conflict Governance Summary

**Long-term memory now behaves like evolving facts: replaceable slots can supersede old versions, ambiguous conflicts are held for review, and search can opt into historical fact states**

## Performance

- **Duration:** 1 session
- **Completed:** 2026-04-16
- **Tasks:** 4
- **Files modified:** 3

## Accomplishments

- Added fact lifecycle metadata for long-term memories, including `fact_key`, `status`, `valid_from`, `valid_to`, `supersedes`, and `superseded_by`.
- Introduced write-time conflict governance so replaceable fact slots auto-supersede previous active facts, while ambiguous slots are stored as `conflict_review` entries with explicit review metadata.
- Updated hybrid search to default to active long-term facts while supporting `include_history` and status-filtered recall for superseded or review-pending fact history.
- Extended consolidate so it can repair legacy active fact chains by converting older active versions into superseded historical entries.
- Preserved Codex adapter compatibility by falling back to explicit long-term splitting when `memory_route` is unavailable.

## Files Created/Modified

- `backend/main.py` - Added fact lifecycle metadata helpers, long-term supersede/review logic, history-aware search filtering, cache schema extensions, and consolidate-based fact-chain repair.
- `tests/test_backend_baseline.py` - Added coverage for supersede, conflict-review, history recall, and legacy fact-chain consolidation.
- `adapters/codex/mcp_server.py` - Restored explicit long-term splitting fallback for older clients without `memory_route`.
- `.planning/phases/06-temporal-facts-and-conflict-governance/06-VERIFICATION.md` - Records verification evidence and requirement coverage for the phase.

## Decisions Made

- Only low-risk, replaceable fact slots auto-supersede in-line; higher-risk durable facts require explicit review rather than silent replacement.
- Historical fact entries are stored as normal memory rows with lifecycle metadata so explainability, audit, and later governance passes can all read the same state model.

## Deviations from Plan

- The original plan mentioned a separate review queue; this iteration ships the minimal structured version as `conflict_review` memory states rather than a standalone queue surface.

## Issues Encountered

- Full-suite regression testing exposed a Codex adapter compatibility gap around `memory_route`; the phase now includes a safe fallback so older clients still restore explicit long-term splitting.

## User Setup Required

None - no extra services or manual migration steps were required.

## Next Phase Readiness

Phase 06 now gives Phase 07 a stronger semantic foundation: long-term memory has explicit lifecycle states, default retrieval can filter history safely, and background maintenance can repair stale fact chains instead of only text duplicates.
No blockers identified for Phase 07.

---
*Phase: 06-temporal-facts-and-conflict-governance*
*Completed: 2026-04-16*
