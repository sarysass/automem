# Testing Architecture Integration: v1.1

**Project:** automem
**Milestone:** v1.1 Testing Depth & Real-World Regression
**Researched:** 2026-04-16
**Confidence:** HIGH
**Scope:** How new testing depth should integrate with the existing API, worker, scheduler, search, task, and shared-memory architecture. This document is only about the testing architecture for the new milestone, not a redesign of the production system.

## Executive Recommendation

automem should add a **three-layer testing architecture** on top of the current control plane:

1. **Deep-user API E2E** using the real FastAPI app, temporary SQLite state, and the existing fake memory backend for determinism.
2. **Cross-runtime workflow tests** using a lightweight live backend harness so the CLI, scheduler, worker, and selected adapter entrypoints all exercise the same HTTP contract.
3. **Failure-recovery unit tests** around queue, lock, retry, lease, and malformed-response behavior at the current backend/script seams.

The production architecture should remain mostly unchanged. The backend should stay the source of truth for governance, search, task state, and background job orchestration. The worker and scheduler should remain thin HTTP clients with no direct database access. Adapters and the CLI should remain wrappers over shared backend APIs. The milestone should add **test harnesses and scenario layers**, not a parallel test-only implementation path inside production code.

## Existing Boundaries To Preserve

These are the right boundaries already. The new test system should reinforce them rather than bypass them.

| Existing boundary | Keep unchanged? | Why |
|-------------------|-----------------|-----|
| `backend/main.py` remains the composition root for API, search, task registry, audit log, and governance job orchestration | Yes | The test system should prove current behavior, not invent an alternate control plane |
| SQLite remains the operational state store for `tasks`, `governance_jobs`, `audit_log`, and `memory_cache` | Yes | The core regression risk is in state transitions across this shared DB |
| `MEMORY_BACKEND` remains swappable in tests via `tests/conftest.py` | Yes | Deterministic tests matter more than using real mem0/Qdrant everywhere |
| `scripts/scheduled_consolidate.py` and `scripts/governance_worker.py` remain HTTP-only runners | Yes | This protects the runtime split and keeps operators using the same contract as tests |
| CLI and adapters remain thin clients over backend HTTP APIs | Yes | Cross-runtime tests should verify shared behavior across wrappers, not duplicate server rules locally |
| Existing focused test suites stay in place | Yes | They are fast guardrails; the new suites should complement them, not replace them |

## Recommended Test Architecture

### Layer 1: Deep-User API E2E

This is the primary new layer. It should run against the real FastAPI app through `TestClient`, backed by a temporary SQLite database and the existing `FakeMemory`.

**Purpose**
- Verify real user-visible workflows across routing, storage, search, task materialization, queue submission, worker execution, and final retrieval.
- Assert behavior through API contracts first, not through direct helper calls.

**Recommended new test components**
- `tests/test_deep_user_workflows_e2e.py`
- `tests/support/scenarios.py`
- `tests/support/assertions.py`

**What it should cover**
- Mixed route flow: `/memory-route` -> `/memories` + `/task-summaries` -> `/search` -> `/tasks`
- Search-and-task continuity: a stored task remains discoverable through both task APIs and hybrid search
- Governance lifecycle: `/governance/jobs` -> `/governance/jobs/run-next` -> `/metrics` -> `/audit-log`
- Project-bound identity safety inside realistic multi-step flows
- Consolidation side effects on memory dedupe, task normalization, and audit traces

**Why this layer should use `TestClient` instead of a subprocess server**
- It is faster and deterministic.
- It reuses the existing fixture model in `tests/conftest.py`.
- It exercises the real app with lifespan/bootstrap behavior and current auth enforcement.
- It avoids making live-network orchestration the default for every regression test.

### Layer 2: Cross-Runtime Workflow Tests

This is the second new layer. It should stand up a lightweight live backend server for tests that must use real HTTP clients and environment-based entrypoints.

**Purpose**
- Prove that non-FastAPI entry surfaces still honor the same backend contract.
- Catch drift between API semantics and wrapper behavior in the CLI, scheduler, worker, and selected adapters.

**Recommended new test components**
- `tests/test_cross_runtime_workflows.py`
- `tests/support/live_backend.py`
- `tests/support/runtime_drivers.py`

**Recommended live harness design**
- Start the real backend app on an ephemeral local port inside pytest.
- Use temporary `TASK_DB_PATH` and `HISTORY_DB_PATH`.
- Keep `FakeMemory` as the default backend for this lane too.
- Pass `MEMORY_URL`, `MEMORY_API_KEY`, and other env vars to runtime wrappers exactly as production does.

**What this layer should cover**
- CLI workflow against a live backend:
  `cli/memory capture` -> `cli/memory search` -> `cli/memory task-list`
- Scheduler/worker workflow against a live backend:
  `scripts/scheduled_consolidate.py` enqueues -> `scripts/governance_worker.py` claims and executes
- Cross-surface consistency:
  a task created by one runtime is visible to another runtime through the shared backend
- One representative adapter lane per runtime family:
  Python-side helper lane first, Node-side adapter lane second

**Important constraint**
- Do not make this a full external-runtime matrix for every adapter on every scenario. That will be brittle and slow.
- Use a small scenario corpus and one representative entrypoint per runtime family.

### Layer 3: Failure-Recovery Unit Tests

This layer should harden the fragile edges that sit below the workflow level.

**Purpose**
- Protect queue and script behavior that is easy to regress but hard to notice manually.
- Keep operational behavior covered even when a full live workflow is too heavy for a focused test.

**Recommended new test components**
- `tests/test_governance_job_recovery.py`
- `tests/test_worker_recovery_unit.py`
- `tests/test_scheduler_recovery_unit.py`

**What it should cover**
- Job enqueue idempotency remains stable
- Lease expiry allows a running job to be reclaimed
- `dispatch_governance_job()` releases jobs back to `pending` until `max_attempts`, then fails
- Scheduler retries on non-200 responses and rejects malformed 200 payloads
- Worker surfaces `idle` versus `processed` behavior cleanly
- Lock-file skip behavior remains explicit and machine-readable

**What not to force into this milestone**
- Stale-lock recovery does not exist yet; do not invent test-only behavior for it
- Backoff/dead-letter scheduling does not exist yet; testing should capture current semantics and flag deeper changes separately

## New Test Layers Vs Production Changes

The milestone should be mostly additive in `tests/`.

| Area | New or modified? | Recommendation |
|------|-------------------|---------------|
| `tests/conftest.py` | Modify | Extend it with a live-backend fixture and shared scenario helpers; keep the current `client` and `backend_module` fixtures |
| `tests/test_backend_baseline.py` | Minimal modify | Keep as the broad backend regression suite; do not keep stuffing deep workflows into it |
| `tests/test_governance_worker.py` | Keep mostly unchanged | Leave it unit-focused on the script boundary; add live orchestration in a new sibling suite |
| `tests/test_scheduled_consolidate.py` | Keep mostly unchanged | Leave it unit-focused on lock/payload/response contracts; add live enqueue flow elsewhere |
| New deep-user E2E suite | Add | Put multi-step user workflows in a dedicated file |
| New cross-runtime suite | Add | Use a live server and environment-driven entrypoints |
| New failure-recovery suite | Add | Focus on queue, lease, retry, and malformed-response semantics |
| Production API surface | Keep unchanged | No new testing-only endpoints |
| Worker/scheduler scripts | Keep unchanged by default | Only refactor if a tiny extraction improves testability without changing behavior |
| Adapters/CLI | Keep unchanged by default | Tests should consume them as-is through their public/runtime-facing entrypoints |

## Explicit Integration Points

The new test system should integrate at these existing seams.

### 1. API Hot Path

Use the current endpoints directly:

- `/memory-route`
- `/memories`
- `/task-summaries`
- `/search`
- `/tasks`
- `/tasks/{task_id}/close`
- `/tasks/{task_id}/archive`
- `/metrics`
- `/audit-log`
- `/runtime-topology`

**Reason**
- These are the observable product contracts.
- Deep-user regression tests should assert from the outside in.

### 2. Governance Job Queue

Use the current queue endpoints directly:

- `/governance/jobs`
- `/governance/jobs/{job_id}`
- `/governance/jobs/run-next`

**Reason**
- The existing API already models idempotency, claim/lease, and completion/failure transitions.
- The test architecture should verify those transitions, not bypass them with internal helper calls only.

### 3. Scheduler And Worker Scripts

Integrate through:

- `scripts/scheduled_consolidate.py:main()` and `run_consolidation()`
- `scripts/governance_worker.py:main()` and `run_once()`

**Reason**
- These are the production entrypoints operators actually run.
- Current unit tests already treat them as thin wrappers; the missing piece is a live HTTP workflow around them.

### 4. Search And Task State

Assert side effects through:

- `/search` results and explainability metadata
- `/tasks` list/detail responses
- `/metrics` task/job counts
- `/audit-log` event traces

**Reason**
- The risky regressions are not just “did the endpoint return 200.”
- The real question is whether routing, storage, dedupe, task normalization, and retrieval stay internally consistent.

### 5. Runtime Wrappers

Integrate through public entry surfaces only:

- `cli/memory`
- selected adapter helper APIs already covered by repo tests

**Reason**
- Cross-runtime tests should validate backend contract parity.
- They should not reach into backend internals from the wrapper side.

## Recommended Data Flow To Test

The strongest milestone scenario is a single deep-user workflow that crosses all existing architectural layers.

```text
Runtime wrapper or API caller
  -> /memory-route
  -> /memories and/or /task-summaries
  -> SQLite task registry + memory cache + audit log update
  -> /search and /tasks verification
  -> /governance/jobs enqueue
  -> worker claims via /governance/jobs/run-next
  -> consolidation mutates task/memory state
  -> /search, /tasks, /metrics, /audit-log final verification
```

This is the right backbone because it exercises:

- hot-path governance
- task materialization
- hybrid retrieval
- queue orchestration
- background execution
- final state observability

## Scenario Design Recommendations

Use a small number of high-value scenarios and run them through multiple layers rather than inventing many narrow cases.

### Scenario A: Mixed Memory + Task Capture

**Start**
- User message contains both durable context and an active work item

**Assert**
- `/memory-route` returns `mixed`
- long-term entries are stored
- task summary is materialized
- search returns the durable fact
- task list returns the active task

### Scenario B: Project-Scoped Regression Protection

**Start**
- Admin seeds two projects
- scoped key performs search/task operations

**Assert**
- allowed project data remains visible
- disallowed project data remains hidden
- multi-step flow keeps project identity enforced at every step

### Scenario C: Consolidation Through Queue

**Start**
- Duplicate long-term entries and noisy task state exist

**Assert**
- scheduler enqueues one job with expected idempotency semantics
- worker claims and completes it
- job result shows `runtime_path = governance_worker`
- duplicates are removed and task state is normalized

### Scenario D: Failure And Retry

**Start**
- consolidation or dispatch path is forced to raise

**Assert**
- job returns to `pending` before `max_attempts`
- job becomes `failed` at exhaustion
- audit/metrics reflect the failure path

## What Should Remain Unchanged

These are deliberate non-goals for this milestone.

### Production logic should not gain test-only branches

Do not add:
- special testing endpoints
- alternate in-memory job queues
- script-only shortcuts that bypass backend auth or queue state
- adapter-local governance logic for the sake of tests

### The runtime split should remain the same

Do not collapse worker logic back into the API just because E2E tests are being added.

- Inline `/consolidate` can remain for existing diagnostics and focused tests.
- Queue-backed execution should stay the primary path for realistic workflow regression tests.

### `tests/conftest.py` should remain the fixture hub

Do not replace the current fixture strategy with an entirely different test bootstrap model.

- Extend it.
- Reuse `FakeMemory`.
- Add a live-backend fixture alongside the current `TestClient` fixture.

### Existing unit suites should keep their role

- `tests/test_governance_worker.py` and `tests/test_scheduled_consolidate.py` stay unit-level.
- `tests/test_identity_e2e.py` stays focused on identity/scope protection.
- `tests/test_backend_baseline.py` stays the broad backend API regression suite.

The new milestone should add a dedicated workflow layer rather than turning every existing file into a mixed-purpose suite.

## Minimal Production Refactors That Are Acceptable

These are acceptable only if the new tests are awkward without them, and only if behavior stays unchanged.

| Refactor | Accept? | Why |
|---------|---------|-----|
| Extract small queue/search/task helpers out of `backend/main.py` into importable modules | Yes, if behavior-preserving | This can reduce test setup friction without changing contracts |
| Add test support helpers under `tests/support/` | Yes | Best place for new harness logic |
| Change endpoint shapes for convenience | No | The tests should adapt to the product contract, not vice versa |
| Add direct DB access to worker/scheduler scripts | No | That would break the current runtime split |
| Replace `FakeMemory` as the default test backend | No | It would make the suite slower and less deterministic |

## Suggested Build Order

The milestone should be built in this order.

1. **Shared test harness layer**
   - Extend `tests/conftest.py`
   - Add `tests/support/` helpers
   - Add a live backend fixture for HTTP-only runtimes
   - Rationale: every later layer depends on stable scenario setup

2. **Deep-user API E2E**
   - Add a dedicated workflow suite using `TestClient`
   - Lock down the canonical user journeys first
   - Rationale: this proves the control plane behavior before wrapper complexity enters

3. **Failure-recovery unit coverage**
   - Backfill queue/lease/retry/lock semantics in focused unit suites
   - Rationale: protects the operational edges that workflow tests will exercise

4. **Scheduler/worker live orchestration**
   - Run `scheduled_consolidate` and `governance_worker` against the live backend fixture
   - Rationale: this is the first realistic end-to-end background-governance lane

5. **Cross-runtime workflow matrix**
   - Reuse the same scenario corpus through CLI and selected adapter wrappers
   - Start with one representative Python lane and one representative Node lane
   - Rationale: highest realism, but most harness complexity

6. **Optional compatibility lane with real mem0/Qdrant**
   - Keep this as a narrow smoke/integration lane, not the default pytest path
   - Rationale: valuable, but not required to structure the milestone around

## Research Flags

These are important, but they are not reasons to redesign the product in this milestone.

| Topic | Why it matters | Recommendation |
|------|----------------|---------------|
| Stale lock recovery | Current scripts only skip when the lock exists | Test current behavior now; treat stale-lock repair as a later product change |
| Retry pacing/backoff | Jobs currently return to `pending` immediately on failure | Cover existing semantics in tests; add backoff only in a follow-up architecture change |
| Real mem0/Qdrant coverage | Current tests mostly use `FakeMemory` | Add one narrow compatibility lane later, not as the default v1.1 architecture |
| `backend/main.py` size | Extraction may help test readability | Only refactor behind existing contracts if tests become unwieldy |

## Bottom Line

The right move for v1.1 is to **add a test architecture around the existing control plane**, not to redesign the control plane for testing.

Add:
- a shared test harness layer
- a dedicated deep-user E2E suite
- a live-backend cross-runtime suite
- focused failure-recovery unit suites

Keep unchanged:
- backend-owned governance
- SQLite-backed operational state
- HTTP-only worker/scheduler scripts
- thin wrappers in CLI and adapters
- the current fixture strategy centered on `tests/conftest.py`

That gives the milestone realistic regression coverage while preserving the production boundaries v1.0 intentionally established.

## Sources

- `.planning/PROJECT.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/CONCERNS.md`
- `backend/main.py`
- `scripts/scheduled_consolidate.py`
- `scripts/governance_worker.py`
- `tests/conftest.py`
- `tests/test_backend_baseline.py`
- `tests/test_governance_worker.py`
- `tests/test_scheduled_consolidate.py`
- `tests/test_identity_e2e.py`
