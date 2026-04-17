# Requirements: automem v1.1 Testing Depth & Real-World Regression

**Defined:** 2026-04-16
**Core Value:** Turn noisy agent output into trustworthy shared memory and task state that multiple agents can reuse safely.

## v1 Requirements

Requirements for the v1.1 testing milestone. These focus on proving existing product behavior through realistic regression coverage.

### Harness Foundation

- [x] **HARN-01**: Maintainer can run a shared live-process test harness that boots the API with isolated temp state and deterministic test dependencies.
- [x] **HARN-02**: Maintainer can run worker and scheduler tests against the same isolated harness without adding test-only production endpoints.
- [x] **HARN-03**: Maintainer can classify tests into fast and slow lanes so routine PR validation stays quick while deeper integration coverage remains available.

### Deep-User Workflows

- [ ] **E2E-01**: Maintainer can verify an end-to-end workflow from memory/task submission through retrieval and observable state changes using named deep-user scenarios.
- [ ] **E2E-02**: Maintainer can verify temporal fact supersede and conflict-review flows through real API scenarios instead of isolated helper assertions.
- [ ] **E2E-03**: Maintainer can verify task lifecycle workflows, including task materialization, follow-up retrieval, and cleanup side effects, through realistic regression scenarios.

### Authorization And Scope Safety

- [ ] **AUTH-01**: Maintainer can verify cross-scope authorization behavior across memory, task, search, close, archive, and forget actions with regression tests that prove fail-closed boundaries.
- [ ] **AUTH-02**: Maintainer can verify single-project, multi-project, and admin access paths through end-to-end tests that catch scope leakage across API surfaces.

### Queue, Worker, And Scheduler Orchestration

- [ ] **ORCH-01**: Maintainer can verify governance job enqueue, claim, execution, and completion through tests that exercise the real API-to-worker handoff.
- [ ] **ORCH-02**: Maintainer can verify scheduled consolidation enqueue behavior, worker consumption, and resulting state transitions through realistic orchestration tests.
- [ ] **ORCH-03**: Maintainer can verify observability side effects for background governance flows, including job state, metrics, and audit evidence.

### Failure Recovery

- [ ] **FAIL-01**: Maintainer can verify poisoned-job retry and exhaustion behavior through tests that prove the system reaches the correct stable failure state.
- [ ] **FAIL-02**: Maintainer can verify lock contention and skip behavior for scheduler and worker flows without overstating stale-lock recovery semantics.
- [ ] **FAIL-03**: Maintainer can verify malformed downstream responses and degraded governance conditions through tests that prove safe failure behavior.

### Risk-Weighted Unit Coverage

- [ ] **UNIT-01**: Maintainer can verify core rule behavior for task classification, cleanup heuristics, and non-work suppression with direct unit tests over edge cases.
- [ ] **UNIT-02**: Maintainer can verify project-scope enforcement, fact lifecycle transitions, and queue-state helpers with focused unit tests that localize regressions quickly.
- [ ] **UNIT-03**: Maintainer can verify failure-path helpers for retries, leases, and response validation with unit tests that avoid mock-only confidence.

### Quality Gates

- [ ] **QUAL-01**: Maintainer can run CI lanes that separate fast default coverage from slower integration or canary coverage with explicit markers and commands.
- [ ] **QUAL-02**: Maintainer can measure milestone completion using named regression stories and critical-path checks instead of a vanity global coverage percentage alone.

## v2 Requirements

Deferred to a future milestone after the core testing system is in place.

### Advanced Testing Depth

- **ADV-01**: Maintainer can run a narrow real-dependency contract lane for mem0/Qdrant-backed behavior in automated CI.
- **ADV-02**: Maintainer can run property-based or stateful testing for fact lifecycle and task-governance invariants.
- **ADV-03**: Maintainer can run OpenAPI-driven fuzz or stateful scenario generation for selected backend flows.

## Out of Scope

Explicitly excluded from this milestone.

| Feature | Reason |
|---------|--------|
| Full browser E2E expansion | This milestone is about backend workflow confidence, not UI/browser coverage |
| Broad adapter-fleet runtime matrix | A representative slice is enough for now; full runtime expansion would dilute backend testing depth |
| Always-on real-stack CI with Docker/Ollama/Qdrant on every PR | Too slow and flaky for the default feedback loop |
| Vanity repo-wide coverage target as the primary success metric | The milestone should optimize for real regression protection, not cosmetic percentages |
| Large production refactor of `backend/main.py` as primary scope | Structural cleanup is valuable, but it would distract from the test-system objective |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HARN-01 | Phase 10 | Validated |
| HARN-02 | Phase 10 | Validated |
| HARN-03 | Phase 10 | Validated |
| E2E-01 | Phase 14 | Pending |
| E2E-02 | Phase 14 | Pending |
| E2E-03 | Phase 14 | Pending |
| AUTH-01 | Phase 14 | Pending |
| AUTH-02 | Phase 14 | Pending |
| ORCH-01 | Phase 12 | Planned |
| ORCH-02 | Phase 12 | Planned |
| ORCH-03 | Phase 12 | Planned |
| FAIL-01 | Phase 12 | Planned |
| FAIL-02 | Phase 12 | Planned |
| FAIL-03 | Phase 12 | Planned |
| UNIT-01 | Phase 14 | Pending |
| UNIT-02 | Phase 14 | Pending |
| UNIT-03 | Phase 12 | Planned |
| QUAL-01 | Phase 13 | Planned |
| QUAL-02 | Phase 13 | Planned |

**Coverage:**
- v1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-16*
*Last updated: 2026-04-17 after planning milestone gap-closure phases 14-15*
