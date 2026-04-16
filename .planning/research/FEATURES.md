# Feature Landscape: v1.1 Testing Depth & Real-World Regression

**Domain:** Mature backend testing milestone for a shared-memory control plane
**Researched:** 2026-04-16
**Confidence:** HIGH for must-have categories, MEDIUM for optional advanced tooling

## Milestone Focus

This milestone should add testing capabilities, not new product surface. The backend already has auth hardening, governance, task registry, search explainability, temporal facts, and a worker split. v1.1 should prove those capabilities under realistic workflows, failure conditions, and regression pressure.

Recommendation: treat this as a backend reliability milestone. The goal is not "more tests"; the goal is durable evidence that core user journeys and operational failure paths still work as the system evolves.

## Table Stakes

These are must-have for this milestone. If they are missing, the testing upgrade will still feel shallow.

| Feature | Why Expected | Complexity | Dependencies / Architecture Notes |
|---------|--------------|------------|-----------------------------------|
| Deep-user workflow scenario suite | A mature backend should prove complete stories, not only isolated endpoints. For automem that means memory capture, search, fact supersession/conflict handling, task materialization, consolidation, and retrieval in one narrative. | High | Build on `tests/conftest.py`, current `TestClient` usage, existing auth helpers, task registry, temporal fact lifecycle, and search explainability endpoints. |
| Cross-scope authorization regression matrix | Fail-closed identity is a core product promise. Project-bound, multi-project, and admin scopes need scenario coverage across read, write, search, close, archive, and forget actions. | Medium | Extends patterns already present in `tests/test_identity_e2e.py`; depends on current API key model and project-scoped enforcement. |
| API-worker-scheduler orchestration tests | For a control plane with background governance, users expect queued jobs, worker pickup, retry state, and cron-style enqueue behavior to be proven together. | High | Must exercise `scripts/scheduled_consolidate.py`, `scripts/governance_worker.py`, `/governance/jobs`, `/governance/jobs/run-next`, SQLite job state, and lock-file behavior together instead of only mocked clients. |
| Failure and recovery regression coverage | High-value backends must prove behavior when dependencies or runtime assumptions break: invalid auth, lock contention, repeated job failure, stale locks, malformed job payloads, and degraded governance decisions. | High | Depends on current governance queue, lock files, audit behavior, and judge fallback boundaries identified in `.planning/codebase/CONCERNS.md`. |
| Risk-weighted unit backfill for core rules | The hot-path rules that decide task classification, fact state, project scoping, and cleanup should have direct edge-case tests so failures localize quickly. | Medium | Best added around pure helpers or loader-based imports from `backend/main.py`; current `pytest.mark.parametrize` style in `tests/test_task_governance_targets.py` is the right starting pattern. |
| Minimal real-dependency integration canary | The current suite mostly swaps in `FakeMemory`. A mature backend needs at least one disposable test lane that verifies the real mem0-backed path and search plumbing so production-only regressions do not slip through. | High | Depends on env-based runtime config in `tests/conftest.py`; best implemented as an opt-in or nightly lane with disposable services rather than every-PR default. |
| Test-suite governance in CI | A serious testing milestone needs fast and slow lanes, markers, and targeted coverage gates so the suite stays useful instead of becoming slow and ignored. | Medium | `pytest-cov` is already installed and CI already runs `uv run pytest`; add markers like `integration` / `real_stack` / `slow`, plus branch- or critical-path-focused coverage gates. |

## Differentiators

These are nice-to-have. They add depth and future leverage, but they should come after the table stakes are green and stable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| OpenAPI-driven stateful API fuzzing | Catches linked-operation bugs that example tests miss, especially create-search-delete or create-close-archive flows. | High | Strong fit once the OpenAPI surface is stable enough to support Schemathesis stateful testing. |
| Property/state-machine testing for fact and task rules | Great for temporal facts, supersession, conflict review, and task normalization where many input combinations map to a few invariants. | Medium-High | Best used on pure logic seams, not on the entire monolith. Hypothesis is valuable here after helper extraction or targeted imports exist. |
| Reproducible regression replay pack | Turns real bugs or milestone concerns into permanent executable scenarios, which is especially valuable for governance, search ranking, and queue recovery issues. | Medium | High product value because it converts prior surprises into durable safety rails. |
| Fault-injection harness for external boundaries | Makes it cheap to simulate network failures, malformed LLM responses, queue corruption, or storage degradation without hand-writing every one-off test. | High | Worth it if automem expects regular reliability work after v1.1; otherwise implement only the highest-risk failures directly. |
| Explainability and audit evidence snapshots | Helpful for detecting drift in search reasons, governance outputs, and operator-facing responses. | Medium | Use sparingly and only on stable, intentionally curated payload fragments. |

## Anti-Features

These should be explicitly excluded from this milestone.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Chasing one big repo-wide coverage number | Inflates low-value tests and rewards easy lines over risky behavior. | Gate critical modules and important branches, not vanity totals. |
| Full browser E2E or adapter-fleet expansion | The milestone is about backend regression depth, not UI polish or every runtime permutation. | Keep frontend and adapter checks narrow; deepen backend workflow coverage first. |
| Running the full real-service stack on every PR | Feedback will get slow and flaky, and the suite will be bypassed. | Keep a fast default PR lane and move real-stack canaries to opt-in or nightly CI. |
| Snapshotting whole JSON payloads indiscriminately | Creates brittle tests that fail on harmless wording or ordering drift. | Assert stable invariants and only snapshot carefully selected evidence fields. |
| Retrying flaky tests until they pass | Hides race conditions and turns operational bugs into silent debt. | Fix determinism with better fixtures, polling, and explicit state checks. |
| Performance/load testing as a substitute for regression coverage | Important later, but it does not answer whether user workflows and failure paths still behave correctly. | Defer load testing to a later operational milestone. |
| Large-scale test-driven refactor of `backend/main.py` as milestone scope | The monolith is real tech debt, but making structural cleanup the centerpiece will derail the testing objective. | Add tests around current seams first; let the test suite make future extraction safer. |

## Feature Dependencies

```text
Shared scenario builders + fixture cleanup
  -> deep-user workflow suite
  -> cross-scope auth matrix
  -> curated regression replay pack

Governance queue harness
  -> worker/scheduler orchestration tests
  -> failure/recovery coverage

Real service provisioning
  -> mem0-backed canary lane
  -> future stateful or fuzz testing against real wiring

Stable OpenAPI links / schema quality
  -> Schemathesis stateful testing

Pure-rule test seams
  -> risk-weighted unit backfill
  -> Hypothesis/property testing
```

## Must-Have vs Nice-to-Have

**Must-have for v1.1**

1. Deep-user workflow scenarios that cover the end-to-end control-plane story.
2. Queue/worker/scheduler integration tests with real job handoff and lock behavior.
3. Failure and recovery coverage for the highest-risk backend failure modes.
4. Cross-scope auth regression coverage across task and memory actions.
5. Unit backfill for core policy rules and edge conditions.
6. CI structure that separates fast PR tests from slower integration lanes.

**Nice-to-have sophistication**

1. Schemathesis stateful runs against the OpenAPI surface.
2. Hypothesis-based invariant testing for temporal facts and task normalization.
3. A reusable fault-injection layer rather than a few direct failure tests.
4. Curated explainability or audit snapshots.

## MVP Recommendation

Prioritize this order:

1. **Scenario builders plus 3-5 deep-user workflows**
   Cover the highest-value stories: scoped memory write/search, temporal fact supersession/conflict, task summary to task lifecycle, consolidation side effects, and explainable retrieval.

2. **Governance queue integration lane**
   Add end-to-end tests that enqueue jobs, run the worker, verify retry transitions, and prove scheduler/worker lock behavior without relying only on fakes.

3. **Failure-path coverage**
   Focus on the concerns already called out in the codebase: stale lock behavior, poisoned job retries, malformed governance responses, and fail-closed auth leakage checks.

4. **Critical-rule unit backfill**
   Add direct unit tests for task classification, project-scope enforcement, fact-status transitions, and cleanup heuristics. This is the fastest way to raise confidence without bloating runtime.

5. **One real-stack canary lane**
   Add a small, disposable integration lane for the real memory backend path. Keep it gated so PR feedback stays fast.

Defer:

- Full adapter or browser E2E
- Load or performance benchmarking
- Large golden snapshot suites
- Broad property-based or stateful fuzzing until the core scenario harness is stable

## Sources

- Local codebase:
  - `.planning/PROJECT.md`
  - `.planning/codebase/TESTING.md`
  - `.planning/codebase/CONCERNS.md`
  - `README.md`
  - `tests/conftest.py`
  - `tests/test_backend_baseline.py`
  - `tests/test_identity_e2e.py`
  - `tests/test_task_governance_targets.py`
  - `tests/test_scheduled_consolidate.py`
  - `tests/test_governance_worker.py`
  - `.github/workflows/ci.yml`
  - `pyproject.toml`
- Official documentation:
  - FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
  - FastAPI async tests: https://fastapi.tiangolo.com/advanced/async-tests/
  - FastAPI lifespan testing: https://fastapi.tiangolo.com/advanced/testing-events/
  - pytest fixtures and parametrization: https://docs.pytest.org/en/stable/how-to/fixtures.html and https://docs.pytest.org/en/stable/how-to/parametrize.html
  - Coverage.py capabilities: https://coverage.readthedocs.io/en/7.13.5/
  - Testcontainers for Python: https://testcontainers-python.readthedocs.io/en/testcontainers-v4.12.0/modules/generic/README.html
  - Hypothesis stateful testing: https://hypothesis.readthedocs.io/en/latest/stateful.html
  - Schemathesis overview and stateful testing: https://schemathesis.readthedocs.io/en/stable/ and https://schemathesis.readthedocs.io/en/stable/guides/stateful-testing/
