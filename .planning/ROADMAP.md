# Roadmap: automem

## Overview

automem v1.0 is shipped, and v1.1 now focuses on proving the shipped control plane under realistic regression pressure. This roadmap keeps the milestone narrow: establish a reusable harness, lock in deep-user and scope-safety scenarios, cover queue/worker/scheduler failure paths, and formalize fast versus slow quality gates without turning the milestone into a browser-E2E push or a production refactor.

## Milestones

- ✅ **v1.0 milestone** — Phases 01-09 (shipped 2026-04-16)
- 🚧 **v1.1 Testing Depth & Real-World Regression** — Phases 10-13 (planned)

## Phases

**Phase Numbering:**
- Integer phases (10, 11, 12, 13): Planned milestone work
- Decimal phases (10.1, 10.2): Urgent insertions if needed later

<details>
<summary>✅ v1.0 milestone (Phases 01-09) — SHIPPED 2026-04-16</summary>

- [x] **Phase 01: Auth Defaults And Tenant Isolation** - Fail closed by default and bind scoped keys safely.
- [x] **Phase 02: Centralize Memory Governance** - Move memory admission into backend-owned policy paths.
- [x] **Phase 03: Stabilize Cache And Consolidation** - Make cache and consolidation flows safer and more deterministic.
- [x] **Phase 04: Shared Identity And Access Model** - Enforce shared project-scoped access across memory and tasks.
- [x] **Phase 05: Retrieval And Explainability** - Improve search quality and make ranking decisions observable.
- [x] **Phase 06: Temporal Facts And Conflict Governance** - Treat durable memory as evolving facts with safe review paths.
- [x] **Phase 07: Runtime Architecture Upgrade** - Split hot-path API work from background governance execution.
- [x] **Phase 08: Foundational Verification Closure** - Backfill the evidence chain for completed product behavior.
- [x] **Phase 09: Milestone Validation Baseline** - Establish milestone-wide Nyquist validation coverage.

</details>

### 🚧 v1.1 Testing Depth & Real-World Regression

**Milestone Goal:** Turn existing capability claims into durable regression protection through realistic workflows, orchestration coverage, failure-path tests, and explicit CI lanes.

- [x] **Phase 10: Test Harness And Lane Foundation** - Create the isolated live-process harness and baseline lane structure every deeper regression suite depends on. (completed 2026-04-16)
- [ ] **Phase 11: Deep-User Workflow And Scope Regression** - Prove core memory, fact, task, and auth flows through named API-first scenarios plus targeted rule backfill.
- [ ] **Phase 12: Orchestration And Failure-Recovery Coverage** - Prove queue, worker, scheduler, retry, and degraded-governance behavior across real handoffs and stable failure states.
- [ ] **Phase 13: Canary And Quality Gates** - Formalize fast/slow governance and milestone-level critical-path checks, including a gated canary lane.

## Phase Details

### Phase 10: Test Harness And Lane Foundation
**Goal**: Maintainers can run a shared, isolated regression harness that boots the real backend and supports worker and scheduler entrypoints without production-only test seams.
**Depends on**: Phase 09
**Requirements**: HARN-01, HARN-02, HARN-03
**Success Criteria** (what must be TRUE):
  1. Maintainer can boot a shared live-process harness that starts the API with deterministic temp state and isolated test dependencies.
  2. Maintainer can run worker and scheduler regression flows against that same harness without adding test-only production endpoints.
  3. Maintainer can classify and invoke fast versus slow test lanes locally without cross-test state leakage or ad hoc per-suite setup.
**Plans**: 3 plans

Plans:
- [x] `10-01-PLAN.md` — Extract shared fake-memory support and build the live backend harness proof.
- [x] `10-02-PLAN.md` — Drive the real scheduler and worker scripts against the shared live harness.
- [x] `10-03-PLAN.md` — Register fast/slow lanes in pytest, CI, and contributor documentation.

### Phase 11: Deep-User Workflow And Scope Regression
**Goal**: Maintainers can prove the highest-value API-first user stories and fail-closed scope boundaries through named regression scenarios backed by focused rule tests.
**Depends on**: Phase 10
**Requirements**: E2E-01, E2E-02, E2E-03, AUTH-01, AUTH-02, UNIT-01, UNIT-02
**Success Criteria** (what must be TRUE):
  1. Maintainer can run named deep-user scenarios from memory or task submission through retrieval and final observable state changes.
  2. Maintainer can verify temporal fact supersede and conflict-review behavior through real API scenarios instead of helper-only assertions.
  3. Maintainer can verify task lifecycle flows, including materialization, follow-up retrieval, and cleanup side effects, through realistic regression stories.
  4. Maintainer can prove fail-closed single-project, multi-project, and admin boundaries across memory, task, search, close, archive, and forget flows while focused unit tests localize regressions in classification, scope, fact lifecycle, and shared state helpers.
**Plans**: TBD

### Phase 12: Orchestration And Failure-Recovery Coverage
**Goal**: Maintainers can prove that background governance behaves correctly from enqueue through completion or safe failure under real worker and scheduler orchestration.
**Depends on**: Phase 11
**Requirements**: ORCH-01, ORCH-02, ORCH-03, FAIL-01, FAIL-02, FAIL-03, UNIT-03
**Success Criteria** (what must be TRUE):
  1. Maintainer can verify governance jobs move through enqueue, claim, execution, and completion via the real API-to-worker handoff, with job state, metrics, and audit evidence visible.
  2. Maintainer can verify scheduled consolidation enqueues work, worker consumption, and resulting state transitions through realistic orchestration tests.
  3. Maintainer can force repeated failures or malformed downstream responses and observe correct stable outcomes for retries, exhaustion, and degraded-governance handling.
  4. Maintainer can verify lock contention and skip behavior, plus failure-path helpers for retries, leases, and response validation, without relying on mock-only confidence.
**Plans**: TBD

### Phase 13: Canary And Quality Gates
**Goal**: Maintainers can run the right depth of regression coverage in the right lane and judge milestone readiness by critical stories instead of vanity metrics.
**Depends on**: Phase 12
**Requirements**: QUAL-01, QUAL-02
**Success Criteria** (what must be TRUE):
  1. Maintainer can run explicit fast and slow test commands, including a gated canary lane, without making the default PR loop behave like an always-on full real stack.
  2. Maintainer can assess milestone readiness through named regression stories and critical-path checks instead of a repo-wide coverage percentage alone.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 10 → 11 → 12 → 13

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 01-09 Archived Milestone Work | 15/15 | Complete | 2026-04-16 |
| 10. Test Harness And Lane Foundation | 3/3 | Complete   | 2026-04-16 |
| 11. Deep-User Workflow And Scope Regression | 0/TBD | Not started | - |
| 12. Orchestration And Failure-Recovery Coverage | 0/TBD | Not started | - |
| 13. Canary And Quality Gates | 0/TBD | Not started | - |
