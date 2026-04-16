# Phase 11: Deep-User Workflow And Scope Regression - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-17
**Phase:** 11-deep-user-workflow-and-scope-regression
**Areas discussed:** Scenario portfolio, Authorization and scope matrix, Fact and task lifecycle evidence, Unit backfill strategy

---

## Scenario portfolio

| Option | Description | Selected |
|--------|-------------|----------|
| Named workflow scenarios | Organize by end-to-end maintainer stories that cross multiple API surfaces and assert final state | ✓ |
| Endpoint buckets | Add deeper coverage per endpoint family with lighter cross-surface linking | |
| Runtime-first stories | Push most deep-user regression into live-process or script-driven flows | |

**User's choice:** Named workflow scenarios
**Notes:** Auto-selected recommended default from the existing roadmap and Phase 10 foundation. The repo already has endpoint coverage; this phase should add story-level protection instead of more isolated endpoint checks.

---

## Authorization and scope matrix

| Option | Description | Selected |
|--------|-------------|----------|
| Fail-closed access matrix | Cover single-project, multi-project, and admin behavior across memory and task surfaces with explicit negative assertions | ✓ |
| Happy-path only | Verify allowed access paths and keep denial behavior mostly in unit tests | |
| Admin-first smoke pass | Focus on admin paths now and defer scoped-key regression to later phases | |

**User's choice:** Fail-closed access matrix
**Notes:** Auto-selected recommended default because `AUTH-01` and `AUTH-02` explicitly require cross-scope fail-closed regression across memory, task, search, close, archive, and forget flows.

---

## Fact and task lifecycle evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Observable state stories | Assert write responses plus retrieval-side state changes for supersede, conflict-review, materialization, close/archive, and cleanup behavior | ✓ |
| Write-path only | Focus on mutation responses and leave retrieval-state assertions to existing baseline tests | |
| Helper-heavy split | Put most lifecycle logic into unit tests with only thin API smoke coverage | |

**User's choice:** Observable state stories
**Notes:** Auto-selected recommended default because the phase goal is to prove realistic regression stories, not helper confidence alone.

---

## Unit backfill strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Helper-focused unit backfill | Add focused unit tests for classification, suppression, cleanup, scope enforcement, and fact lifecycle helpers while leaving orchestration depth to Phase 12 | ✓ |
| Broad endpoint duplication | Mirror the full API stories again at unit level for redundancy | |
| Minimal unit work | Keep almost all new confidence in API-level tests and add only a few helper assertions | |

**User's choice:** Helper-focused unit backfill
**Notes:** Auto-selected recommended default because `UNIT-01` and `UNIT-02` call for fast localization of regressions in stable rules and helpers rather than duplicated integration coverage.

---

## the agent's Discretion

- Exact scenario naming
- Helper extraction and fixture organization
- Parametrization shape for matrix-style regressions

## Deferred Ideas

- Full browser E2E expansion
- Broad adapter/runtime matrix expansion
- Real-dependency contract lanes for mem0 or Qdrant
