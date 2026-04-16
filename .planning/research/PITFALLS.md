# Domain Pitfalls

**Domain:** Regression-test expansion for a shared-memory backend/control plane
**Project:** automem
**Milestone focus:** `v1.1 Testing Depth & Real-World Regression`
**Researched:** 2026-04-16
**Overall confidence:** HIGH

## Executive Summary

The biggest risk in this milestone is not "too few tests." It is building a larger suite that still stops one layer short of reality and therefore increases confidence faster than it increases protection. In automem, that pattern is already visible: backend API tests run through the real FastAPI app, but the memory backend is replaced with `FakeMemory`; scheduler and worker tests prove payload construction and lock-file skip behavior, but they do not exercise the real governance queue, lease recovery, or retry transitions; and there is no suite that follows one realistic flow across API, search, queue, worker, and audit surfaces together.

For this system, the dangerous regressions are cross-surface regressions: project scope leaking between users, governance jobs enqueueing but not executing correctly, stale lock files wedging unattended operation, retries burning through attempts with no pacing, and real `mem0` or retrieval behavior diverging from the simplified fake backend. A test milestone that focuses on endpoint counts or coverage percentage before those seams are covered will create false confidence.

This milestone should therefore be sequenced around risk, not around files or modules. Build the test harness and isolation rules first. Then lock in a small number of deep, cross-surface regression scenarios. Then add failure-recovery and observability assertions. Only after those are stable should the milestone backfill more unit tests around pure policy helpers and edge normalization logic.

## Critical Pitfalls

### Pitfall 1: Treating `FakeMemory`-backed API tests as full system coverage
**Confidence:** HIGH

**What goes wrong:**  
The suite stays green while production breaks in `mem0`, embeddings, vector search, metadata persistence, deletion semantics, or real search ranking.

**Why it happens:**  
`tests/conftest.py` swaps `backend_module.MEMORY_BACKEND` to `FakeMemory`, whose behavior is deliberately simpler than production: in-memory records only, substring search only, no vector store, no embedding calls, no real persistence, no live fallback path.

**Warning signs:**  
- New tests all use `client` from `tests/conftest.py` and none require local disposable services.
- Search tests assert exact ordering against `FakeMemory` substring matches.
- The milestone claims search or storage confidence without any real-backend contract suite.

**Consequences:**  
- Search and retrieval regressions reach production even when pytest is green.
- Metadata and lifecycle bugs are discovered only after deployment.
- The suite starts rewarding fake-friendly implementations over production-correct ones.

**Prevention:**  
- Keep the fast `FakeMemory` suite, but label it clearly as API-contract coverage, not storage/retrieval reality.
- Add a thin real-dependency contract suite for `mem0` wiring with disposable local services and a tiny dataset.
- Assert contract properties, not exact relevance scores: result presence, scoping, persistence, deletion, history visibility, and fallback behavior.

**Sequencing advice:**  
Do this early in `v1.1`, but keep it intentionally small. One or two real-backend scenarios are more valuable than dozens of fake-only route tests.

**Future phase(s) to address deeply:**  
- `Real Dependency Verification`
- `Search/Relevance Tuning`

**Evidence:**  
- `tests/conftest.py:12-71`
- `tests/conftest.py:74-103`
- `.planning/codebase/CONCERNS.md` (`mem0ai` under-tested relative to importance)

### Pitfall 2: Over-mocking scheduler and worker boundaries
**Confidence:** HIGH

**What goes wrong:**  
The scheduler and worker scripts appear covered, but the real queue lifecycle is not. Jobs can enqueue incorrectly, fail to claim, skip lease recovery, or return malformed responses without tests catching it.

**Why it happens:**  
Current script tests patch in fake HTTP clients and assert request shape, response validation, and lock skip behavior. They do not run against the real FastAPI app, real SQLite job rows, or real job dispatch paths.

**Warning signs:**  
- Tests only assert that `FakeClient.post()` was called with the right path.
- No test creates a job through `/governance/jobs` and completes it through `/governance/jobs/run-next`.
- No test inspects resulting queue rows, attempts, lease state, or audit events.

**Consequences:**  
- Operational regressions ship in exactly the unattended paths this milestone is supposed to protect.
- Scripts and backend endpoints drift without detection.
- CI proves request syntax, not system behavior.

**Prevention:**  
- Add cross-surface integration tests that use the real app plus a real temp SQLite DB.
- Exercise `scheduled_consolidate.py` and `governance_worker.py` against an in-process ASGI app or short-lived local server.
- Assert queue state transitions end-to-end: `pending -> running -> completed|failed`, plus emitted audit rows.

**Sequencing advice:**  
This should come before broad unit backfill. Until queue orchestration is covered end-to-end, extra unit tests mostly deepen the wrong confidence.

**Future phase(s) to address deeply:**  
- `Runtime Operations Hardening`
- `Worker/Scheduler Resilience`

**Evidence:**  
- `tests/test_scheduled_consolidate.py:77-188`
- `tests/test_governance_worker.py:23-65`
- `backend/main.py:2216-2538`
- `backend/main.py:4661-4750`

### Pitfall 3: Confusing "lock exists" tests with crash-recovery coverage
**Confidence:** HIGH

**What goes wrong:**  
The suite proves that existing lock files cause a safe skip, but production still wedges indefinitely after a crash because stale locks are never recovered.

**Why it happens:**  
Both scripts use exclusive file creation and treat `EEXIST` as "skip." Current tests only cover the presence of the lock file, not PID validation, TTL expiration, stale-lock cleanup, or operator repair.

**Warning signs:**  
- The milestone reports lock coverage based on skip assertions alone.
- No test simulates a stale lock written by a dead process.
- No test verifies operator-visible diagnostics or recovery tooling.

**Consequences:**  
- Cron- or systemd-driven runs silently stop doing useful work.
- Operators discover issues by absence of progress rather than explicit failure.
- Tests unintentionally canonize today's fragile behavior as the desired design.

**Prevention:**  
- Separate characterization from endorsement: test the current skip behavior, but document it as an operational risk rather than a finished design.
- Add pending or future-facing tests for stale-lock handling once product behavior is defined.
- Require explicit milestone notes for any test that protects a known-bad interim behavior.

**Sequencing advice:**  
In `v1.1`, keep only a small characterization slice here. Do not spend the milestone building a large lock suite until the product has stale-lock recovery semantics to test.

**Future phase(s) to address deeply:**  
- `Operations Recovery Tooling`
- `Runtime Operations Hardening`

**Evidence:**  
- `scripts/scheduled_consolidate.py:36-63`
- `scripts/governance_worker.py:56-83`
- `tests/test_scheduled_consolidate.py:166-188`
- `tests/test_governance_worker.py:41-65`

### Pitfall 4: Missing poisoned-job and retry-loop scenarios
**Confidence:** HIGH

**What goes wrong:**  
Repeated job failures burn through attempts too quickly or loop noisily, but the suite still passes because only single-failure or client-side retry behavior is covered.

**Why it happens:**  
`release_governance_job_for_retry()` immediately moves jobs back to `pending` until `max_attempts` is reached. The worker can then reclaim the same bad job on the next poll. Current tests do not model repeated dispatch failure or pacing.

**Warning signs:**  
- Tests only prove one retry or one success path.
- No test asserts `attempts`, `max_attempts`, `status`, and `error_text` after repeated failures.
- No test proves the final failed state is stable and does not re-run.

**Consequences:**  
- Production can thrash on poisoned jobs.
- Audit logs fill with repeated failures.
- Operators lose trust in background automation because failures are technically "handled" but operationally uncontrolled.

**Prevention:**  
- Add integration tests that force `run_consolidation_operation` to fail repeatedly and assert exact job-state transitions.
- Assert both control-plane results and observability side effects: job row state plus failure audit entry.
- Avoid only testing the script's outer retry loop; the important behavior is inside the queue lifecycle.

**Sequencing advice:**  
Do this right after queue lifecycle coverage. It is one of the highest-value regression targets because it protects unattended failure modes.

**Future phase(s) to address deeply:**  
- `Queue Backoff And Dead-Lettering`
- `Runtime Operations Hardening`

**Evidence:**  
- `backend/main.py:2428-2466`
- `backend/main.py:2469-2538`
- `scripts/governance_worker.py:93-120`
- `.planning/codebase/CONCERNS.md` (retry has no backoff or dead-letter delay)

### Pitfall 5: Testing identity helpers without proving cross-surface authorization
**Confidence:** HIGH

**What goes wrong:**  
Helper-level project/user identity rules pass, but real end-to-end flows still leak scope or allow the wrong key to enqueue, search, consolidate, or retrieve across projects.

**Why it happens:**  
Unit tests correctly cover helpers like `enforce_project_identity`, but regressions in endpoint wiring, payload normalization, queue execution, or background dispatch can bypass that confidence if the tests never run a realistic multi-actor scenario.

**Warning signs:**  
- Security tests stop at helper functions and isolated endpoints.
- No scenario uses at least two users, two projects, and both admin/non-admin keys in the same flow.
- Background job tests always run with admin context only.

**Consequences:**  
- Cross-project leakage reaches production.
- Admin-only endpoints may stay secure in unit tests but drift in full workflows.
- The most severe regression class in automem appears only in deployed use.

**Prevention:**  
- Add end-to-end tests that start with key creation, continue through memory/task creation, then validate search, job enqueue, and worker execution boundaries.
- Use explicitly conflicting actors and projects in the same test so leakage is visible.
- Prefer scenario tests that assert both denial and non-observability: the wrong actor should not see the data, not just receive a 403 on one endpoint.

**Sequencing advice:**  
This belongs in the first wave of deep regression tests. For this product, identity and scope are more critical than raw coverage growth.

**Future phase(s) to address deeply:**  
- `Shared Access Model Expansion`
- `Adapter Compatibility And Contract Verification`

**Evidence:**  
- `tests/test_identity_unit.py:10-39`
- `tests/test_backend_baseline.py:29-56`
- `backend/main.py:4663-4666`
- `backend/main.py:4735-4745`

### Pitfall 6: Chasing coverage percentage instead of deep-user scenarios
**Confidence:** HIGH

**What goes wrong:**  
The repository reports better numbers while still lacking protection for the flows that matter: API admission, search recall, governance enqueue/worker processing, audit evidence, and task-state cleanup.

**Why it happens:**  
Coverage tooling exists but no threshold or risk-weighted scenario list is enforced. That makes it easy to add many cheap tests around pure helpers, response shapes, or happy-path endpoints.

**Warning signs:**  
- Milestone success is described in percentages instead of named scenarios.
- Many new tests target single functions or single endpoints with no shared setup.
- The suite grows quickly but there is still no "one user journey" test crossing multiple surfaces.

**Consequences:**  
- The team gets a misleading sense of completion.
- Reviewers reward easy tests because they move numbers.
- Real regressions survive under an apparently improved suite.

**Prevention:**  
- Define a small required regression matrix first: scope isolation, long-term fact lifecycle, queue handoff, worker failure recovery, scheduled consolidation, search/history visibility.
- Treat percentage metrics as a lagging indicator, not the milestone target.
- Require each new test cluster to map to a product claim or operational risk.

**Sequencing advice:**  
Scenario matrix first, unit backfill second, coverage report last.

**Future phase(s) to address deeply:**  
- `Quality Gate Hardening`

**Evidence:**  
- `.planning/PROJECT.md` (milestone goal is realistic regression protection)
- `.planning/codebase/TESTING.md` (coverage available, no threshold configured)
- `.github/workflows/ci.yml`

## Moderate Pitfalls

### Pitfall 7: Writing brittle tests against monolith internals
**Confidence:** HIGH

**What goes wrong:**  
Tests lock onto internal call order, exact SQL sequencing, or private helper structure inside `backend/main.py`, making the later extraction work much harder.

**Prevention:**  
- Unit-test pure policy helpers directly.
- Test monolith-heavy behavior through public contracts: HTTP responses, DB state, audit rows, and job transitions.
- Avoid assertions on incidental implementation details unless they define an external guarantee.

**Sequencing advice:**  
Black-box integration first. Only add fine-grained unit tests where the code is already pure and intentionally stable.

**Future phase(s) to address deeply:**  
- `Backend Module Extraction`

**Evidence:**  
- `.planning/codebase/CONCERNS.md` (`backend/main.py` monolith)

### Pitfall 8: Ignoring lifespan and event-loop rules in new integration tests
**Confidence:** HIGH

**What goes wrong:**  
Tests become flaky or misleading because startup/shutdown logic does not run, or async resources are mixed across incompatible event loops.

**Prevention:**  
- Keep sync API tests inside `with TestClient(app)` so lifespan runs.
- For async or multi-resource integration, use `AsyncClient` with `ASGITransport` and an explicit `base_url`.
- Standardize this in a shared fixture instead of letting each new suite improvise.

**Sequencing advice:**  
Build the harness once at the start of the milestone. Do not let each test file invent its own client lifecycle.

**Future phase(s) to address deeply:**  
- `Test Harness Hardening`

**Evidence:**  
- `tests/conftest.py:100-103`
- Starlette TestClient docs: <https://www.starlette.dev/testclient/>

### Pitfall 9: Letting environment and module state leak between tests
**Confidence:** HIGH

**What goes wrong:**  
One suite changes env vars, import state, or on-disk DB paths in ways that accidentally affect later suites, producing order-dependent failures.

**Prevention:**  
- Continue using `monkeypatch` and `tmp_path` for per-test isolation.
- Centralize env mutation in fixtures instead of open-coded `os.environ` edits.
- Avoid reusing imported modules with mutable globals across tests unless teardown is explicit.

**Sequencing advice:**  
Treat fixture cleanup as milestone infrastructure, not test polish.

**Future phase(s) to address deeply:**  
- `Test Harness Hardening`

**Evidence:**  
- `tests/conftest.py:74-97`
- `tests/test_scheduled_consolidate.py:23-63`
- pytest docs: <https://docs.pytest.org/en/stable/how-to/monkeypatch.html>
- pytest docs: <https://docs.pytest.org/en/7.1.x/how-to/tmp_path.html>

### Pitfall 10: Missing observability assertions on fallback-heavy paths
**Confidence:** MEDIUM

**What goes wrong:**  
Tests prove that a request returned `200`, but not whether the system took the intended runtime path, emitted the expected audit event, or silently degraded.

**Why it matters here:**  
automem's control plane uses audits, job rows, and runtime-path distinctions to explain what happened. A backend like this can be functionally "successful" while operationally wrong.

**Prevention:**  
- Assert audit rows, job `error_text`, `attempts`, deduplication markers, runtime-path metadata, and history visibility where relevant.
- Promote "did the system tell the truth about what it did?" to a first-class test concern.

**Sequencing advice:**  
Add these assertions while building deep scenarios, not as a later cleanup pass.

**Future phase(s) to address deeply:**  
- `Telemetry And Operator Diagnostics`

**Evidence:**  
- `backend/main.py:2491-2537`
- `backend/main.py:4692-4707`
- `.planning/codebase/CONCERNS.md` (LLM failures degrade silently to heuristics)

## Minor Pitfalls

### Pitfall 11: Freezing current fragile behavior as a permanent contract
**Confidence:** HIGH

**What goes wrong:**  
Tests enshrine today’s temporary compromises, making later hardening look like a regression.

**Prevention:**  
- Mark characterization tests clearly.
- In test names and comments, distinguish "current behavior" from "desired durable behavior."
- Prefer contract tests around product promises, not all observed behavior.

**Future phase(s) to address deeply:**  
- `Runtime Operations Hardening`
- `Backend Module Extraction`

### Pitfall 12: Forgetting adapter-facing contract drift
**Confidence:** MEDIUM

**What goes wrong:**  
The backend suite improves, but adapter request/response expectations drift because adapters are still protected mostly by smoke scripts.

**Prevention:**  
- Add a small compatibility suite that replays representative adapter-facing requests against the shared backend contract.
- Reuse backend fixtures and only keep adapter-specific smoke where adapter packaging differs.

**Future phase(s) to address deeply:**  
- `Adapter Compatibility And Contract Verification`

## How This Milestone Should Avoid Them

Recommended order for `v1.1`:

1. **Build the test harness first**
   - Shared fixtures for real app lifecycle, temp DB isolation, and optional async client usage.
   - Make the "correct way" to write a deep regression test easy before adding many tests.

2. **Lock in security-critical cross-surface scenarios next**
   - Multi-user, multi-project, admin/non-admin flows.
   - Search visibility, memory lifecycle, job enqueue, and worker execution under scoped identities.

3. **Add queue, worker, and scheduler integration after that**
   - Real job lifecycle, idempotency, repeated failure, and final failed-state behavior.
   - One or two real orchestration tests are worth more than many mocked script tests.

4. **Add observability assertions while writing those scenarios**
   - Audit rows, job fields, runtime-path markers, and failure metadata.

5. **Add a thin real-dependency contract slice**
   - Small, slow, high-value suite for real storage/retrieval integration.

6. **Backfill targeted unit tests last**
   - Pure rules, normalization, identity helpers, and edge conditions that are stable and cheap.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Future phase(s) |
|-------------|----------------|------------|-----------------|
| Test harness setup | Each suite invents its own lifecycle and cleanup rules | Centralize `TestClient`/async client, env isolation, and temp DB fixtures first | `Test Harness Hardening` |
| Search regression tests | Fake substring search is mistaken for real retrieval coverage | Keep fake suite fast, add thin real-backend contract suite | `Real Dependency Verification`, `Search/Relevance Tuning` |
| Identity/security scenarios | Helper tests are mistaken for cross-surface authorization proof | Use multi-actor end-to-end flows with conflicting projects and keys | `Shared Access Model Expansion` |
| Worker/scheduler coverage | Mocked HTTP tests are mistaken for orchestration proof | Add real queue lifecycle tests against the app and temp SQLite DB | `Worker/Scheduler Resilience` |
| Failure recovery | Single-error tests miss poisoned-job loops and stale locks | Add repeated-failure queue tests; keep lock behavior as characterization until design improves | `Queue Backoff And Dead-Lettering`, `Operations Recovery Tooling` |
| Coverage tracking | Percentages outrun real protection | Measure milestone completion against named regression scenarios first | `Quality Gate Hardening` |
| Backend refactor safety | Internal-detail tests make extraction painful | Test public contracts and stable pure helpers only | `Backend Module Extraction` |
| Adapter confidence | Backend tests improve while adapter contracts drift | Add shared contract tests for representative adapter requests | `Adapter Compatibility And Contract Verification` |

## Sources

### Local evidence
- `.planning/PROJECT.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/TESTING.md`
- `tests/conftest.py`
- `tests/test_backend_baseline.py`
- `tests/test_identity_unit.py`
- `tests/test_scheduled_consolidate.py`
- `tests/test_governance_worker.py`
- `scripts/scheduled_consolidate.py`
- `scripts/governance_worker.py`
- `backend/main.py`
- `.github/workflows/ci.yml`

### Official docs
- Starlette TestClient docs: <https://www.starlette.dev/testclient/>
  - Supports the lifespan/context-manager and async-client guidance used in the harness recommendations.
- pytest monkeypatch docs: <https://docs.pytest.org/en/stable/how-to/monkeypatch.html>
  - Confirms patch cleanup semantics and scoped patching guidance.
- pytest tmp_path docs: <https://docs.pytest.org/en/7.1.x/how-to/tmp_path.html>
  - Confirms per-test temporary directory isolation.
