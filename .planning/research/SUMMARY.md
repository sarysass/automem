# Project Research Summary

**Project:** automem
**Domain:** Shared-memory and task-governance backend testing/reliability milestone
**Researched:** 2026-04-16
**Confidence:** HIGH

## Executive Summary

automem `v1.1 Testing Depth & Real-World Regression` is a backend reliability milestone, not a feature-expansion milestone. The product is already a shared memory and task-governance control plane with fail-closed identity, hybrid retrieval, temporal fact lifecycle, and a runtime split between the hot-path API and background worker/scheduler flows. The research is consistent: experts would not rebuild the testing stack from scratch here. They would keep the current `pytest` + FastAPI `TestClient` + temp SQLite base, then add a realistic harness layer that proves cross-surface behavior through deep-user workflows, queue orchestration, and failure recovery.

The recommended approach is additive and risk-weighted. Keep fast deterministic tests as the default lane, add a shared test harness plus deep-user API E2E scenarios first, then extend coverage into live worker/scheduler orchestration and poisoned-job recovery. A narrow real-dependency canary for the mem0/Qdrant path is worth adding, but only as an opt-in or nightly lane. The milestone should not center on browser E2E, broad adapter matrices, or chasing a headline coverage number.

The biggest risk is false confidence: expanding the suite while still stopping one layer short of reality. In practice that means over-trusting `FakeMemory`, over-mocking scheduler/worker boundaries, mistaking lock-file skip tests for recovery coverage, and measuring success by line coverage instead of named deep-user regression scenarios. Mitigation is clear from the research: build the harness first, prove a small set of cross-surface workflows, assert observability side effects, and keep real-stack coverage thin but real.

## Key Findings

### Recommended Stack

The stack recommendation is conservative on purpose. automem already has the right foundation, so the milestone should preserve `pytest`, `pytest-cov`, FastAPI `TestClient`, and temp SQLite fixtures while adding only the pieces needed for realistic orchestration and subprocess-proof coverage.

**Core technologies:**
- `pytest` — primary test runner; keep the current `8.4` line to avoid mixing a runner upgrade with harness work.
- `fastapi.testclient.TestClient` — default API integration surface; fastest way to prove real routes, lifespan, auth, and SQLite-backed behavior.
- Temporary SQLite databases — operational-state test store; matches production control-plane risks around tasks, jobs, audit, and cache transitions.
- `coverage[toml]` — subprocess coverage for live API/worker/scheduler tests; required once tests launch real child processes.
- `pytest-timeout` — deadlock and hang protection; important because the system uses locks, retries, and poll loops.
- `respx` — focused `httpx` boundary mocking; better than ad hoc fake clients for failure-path unit tests.
- `asgi-lifespan` — async lifespan support when `httpx.AsyncClient` is needed in harness code.
- `testcontainers` — optional only; use for a narrow Qdrant contract lane, not the default PR workflow.

**Critical version requirements:**
- Keep `pytest>=8.4,<9.0` and `pytest-cov>=7.0,<8.0`.
- Add `coverage[toml]>=7.13,<8.0`, `pytest-timeout>=2.4,<3.0`, `respx>=0.23,<0.24`, and `asgi-lifespan>=2.1,<3.0`.
- Keep `mem0ai` on the current line for this milestone; do not bundle a mem0 major-version migration into testing work.

### Expected Features

This milestone should deliver stronger evidence for existing product claims, not new user-facing capability. The must-haves all center on realistic workflows, failure behavior, and CI governance.

**Must have (table stakes):**
- Deep-user workflow scenario suite — prove end-to-end stories across memory capture, search, fact lifecycle, task materialization, consolidation, and retrieval.
- Cross-scope authorization regression matrix — verify fail-closed project and admin boundaries across read, write, search, close, archive, and forget actions.
- API-worker-scheduler orchestration tests — prove queued jobs, worker pickup, retry behavior, and scheduler lock behavior together.
- Failure and recovery regression coverage — cover poisoned jobs, malformed responses, invalid auth, lock contention, and degraded governance paths.
- Risk-weighted unit backfill — add focused edge-case tests for task classification, fact-state transitions, project scoping, cleanup heuristics, lease/retry behavior, and other hot-path rules.
- Minimal real-dependency integration canary — verify the real mem0-backed/Qdrant wiring in a thin gated lane so fake-backed green runs do not overstate production confidence.
- CI test governance — separate fast default lanes from slower integration/real-stack lanes with explicit markers and targeted coverage expectations.

**Should have (nice-to-have depth):**
- Curated regression replay pack for previously observed bugs and milestone concerns.
- Limited explainability/audit evidence snapshots for stable, operator-facing payload fragments.
- Fault-injection helpers for repeated external-boundary failures if direct tests start becoming repetitive.

**Defer (v2+ or later milestone):**
- Broad OpenAPI-driven Schemathesis/stateful API fuzzing.
- Broad Hypothesis/property-based testing beyond a few pure-rule seams.
- Full browser E2E or large adapter/runtime matrices.
- Load/performance testing as a substitute for workflow regression coverage.
- Any repo-wide test refactor that turns `backend/main.py` cleanup into the real milestone scope.

### Architecture Approach

The architectural recommendation is to add test layers around the existing control plane, not redesign production code for testability. The backend should remain the source of truth for governance, search, task state, and queue orchestration; SQLite should remain the operational state store; worker and scheduler scripts should stay thin HTTP-only clients; and CLI/adapters should keep consuming public backend contracts. The milestone should extend `tests/conftest.py` and add `tests/support/` helpers rather than introduce test-only endpoints or alternate production flows.

**Major components:**
1. Shared test harness layer — centralizes temp-path isolation, env wiring, live backend startup, polling, and reusable scenario builders.
2. Deep-user API E2E suite — proves the canonical user journeys through the real FastAPI app with deterministic test storage.
3. Failure-recovery unit suite — hardens queue, retry, lease, lock, malformed-response, and policy edge cases at focused seams.
4. Live worker/scheduler orchestration suite — drives `scheduled_consolidate` and `governance_worker` against the real backend contract.
5. Optional real-dependency contract lane — verifies mem0/Qdrant compatibility without slowing every PR.

### Critical Pitfalls

1. **Treating `FakeMemory` coverage as full-system proof** — keep fake-backed tests for fast API-contract coverage, but add a thin real-backend contract lane so storage/retrieval drift cannot hide.
2. **Over-mocking scheduler and worker boundaries** — prove real queue transitions end-to-end instead of only asserting request shape on fake clients.
3. **Mistaking lock-file skip tests for crash-recovery coverage** — characterize current skip behavior, but do not claim stale-lock recovery unless product semantics exist and are tested.
4. **Missing poisoned-job and retry-loop scenarios** — add repeated-failure tests that verify `pending -> running -> failed`, attempts accounting, and final stable failure state.
5. **Measuring success by coverage percentage instead of scenario depth** — define milestone completion around named regression stories and observability assertions first, coverage metrics second.

## Implications for Roadmap

Based on the research, suggested phase structure:

### Phase 1: Test Harness And Isolation Foundation
**Rationale:** Everything else depends on deterministic setup, shared fixtures, subprocess coverage wiring, and clean resource isolation.
**Delivers:** Extended `tests/conftest.py`, `tests/support/` helpers, live-backend fixture, polling utilities, temp DB/lock/env isolation, and test markers.
**Addresses:** CI test governance, harness preconditions for deep-user workflows, and the need for stable lifecycles across sync/async/live tests.
**Avoids:** Per-suite lifecycle drift, env leakage, event-loop/lifespan flakiness, and early false negatives from bad test infrastructure.

### Phase 2: Deep-User API Regression Scenarios
**Rationale:** The highest-value confidence gain comes from proving canonical user journeys before adding more runtime complexity.
**Delivers:** A dedicated scenario suite covering scoped memory capture/search, task materialization, temporal fact supersession/conflict, explainable retrieval, and multi-actor authorization flows.
**Addresses:** Deep-user workflow scenarios and cross-scope authorization regression coverage.
**Avoids:** Coverage inflation without real product-story protection, and helper-level auth confidence that misses cross-surface leakage.

### Phase 3: Queue, Worker, Scheduler, And Failure Recovery
**Rationale:** Once core journeys are covered, the next biggest operational risk is unattended background behavior.
**Delivers:** Real job enqueue/claim/complete tests, scheduler lock-path characterization, poisoned-job retry exhaustion tests, lease/retry assertions, and audit/metrics observability checks.
**Uses:** `pytest-timeout`, `coverage[toml]`, `respx`, and the live-backend harness from Phase 1.
**Implements:** Live worker/scheduler orchestration against the existing HTTP queue contract.
**Avoids:** Over-mocked script confidence, untested retry loops, and silent background regressions.

### Phase 4: Real-Dependency Canary And Quality Gates
**Rationale:** After deterministic and orchestration coverage is stable, add one thin reality check for the mem0/Qdrant path and formalize CI lane boundaries.
**Delivers:** A gated real-stack canary lane, marker-based fast/slow CI split, subprocess coverage combine, and milestone-level quality gates tied to named critical scenarios.
**Addresses:** Minimal real-dependency integration coverage and ongoing test-suite governance.
**Avoids:** Over-trusting fake storage behavior and slowing default PR feedback with full real-service bring-up.

### Phase Ordering Rationale

- Harness first because every recommended suite depends on isolated paths, shared env wiring, and condition-based waiting.
- Deep-user API scenarios second because they validate the core product claims with the least harness complexity and the highest immediate confidence return.
- Queue/worker/scheduler orchestration third because it depends on the harness and scenario corpus, and it targets the next highest-risk operational seam.
- Real-dependency canary last because it is valuable but intentionally narrow; it should validate the already-stable regression matrix, not define it.
- Unit backfill should happen inside Phases 2 and 3 as targeted support work, not as a standalone first phase that inflates counts before cross-surface protection exists.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** The exact subprocess-friendly memory-backend seam needs a small implementation decision because current mem0 docs do not provide a clean drop-in local-mode path for automem's `Memory.from_config(...)` setup.
- **Phase 4:** The real-dependency canary needs validation on the narrowest viable mem0/Qdrant contract and CI shape so the lane stays useful without becoming a maintenance tax.

Phases with standard patterns (skip research-phase):
- **Phase 2:** Deep-user API E2E on FastAPI `TestClient` + temp SQLite is well-supported and already aligned with the repo's testing patterns.
- **Phase 3:** Failure-path unit tests around retries, locks, response validation, and queue-state assertions follow established pytest/FastAPI/httpx patterns once the harness exists.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Strong alignment between current repo structure and official pytest/FastAPI/coverage/testcontainers guidance. |
| Features | HIGH | The milestone scope is clear in `PROJECT.md`, and the must-have categories converge across product context and testing research. |
| Architecture | HIGH | The research consistently recommends preserving the existing backend/worker/scheduler boundaries and adding test layers around them. |
| Pitfalls | HIGH | Risks are grounded in the current codebase and existing test gaps, especially around fake-backed coverage, queue orchestration, and failure recovery. |

**Overall confidence:** HIGH

### Gaps to Address

- **Subprocess memory backend seam:** planning should decide whether to add an env-driven deterministic backend hook or another minimal mechanism for live-process tests without requiring Ollama on every run.
- **Real-stack canary scope:** planning should explicitly limit what the mem0/Qdrant lane proves so it does not expand into a second full regression suite.
- **Stale-lock semantics:** current behavior can be characterized in tests, but real stale-lock recovery remains a future product decision rather than a v1.1 acceptance target.
- **Coverage policy shape:** planning should define critical-path expectations by scenario/module, not a vanity global percentage.

## Sources

### Primary (HIGH confidence)
- [.planning/PROJECT.md](../PROJECT.md) — milestone goal, scope, constraints, and active requirements
- [.planning/research/STACK.md](./STACK.md) — stack additions, versions, harness recommendations, CI lane strategy
- [.planning/research/FEATURES.md](./FEATURES.md) — table stakes, differentiators, anti-features, and milestone MVP order
- [.planning/research/ARCHITECTURE.md](./ARCHITECTURE.md) — testing-layer design, preserved boundaries, and build order
- [.planning/research/PITFALLS.md](./PITFALLS.md) — cross-surface failure modes, sequencing warnings, and risk framing
- FastAPI testing docs — API and lifespan testing patterns
- coverage.py subprocess docs — subprocess coverage requirements for live-process tests
- pytest docs — fixtures, monkeypatch, tmp-path isolation, parametrization

### Secondary (MEDIUM confidence)
- RESPX docs — `httpx` mocking guidance for boundary-focused unit tests
- Testcontainers Python docs — optional containerized Qdrant lane guidance
- Qdrant client docs — local-mode capability, with uncertainty about direct fit for automem's current mem0 wiring
- Hypothesis and Schemathesis docs — optional future depth, not required for v1.1

### Tertiary (LOW confidence)
- None material to the core milestone recommendation

---
*Research completed: 2026-04-16*
*Ready for roadmap: yes*
