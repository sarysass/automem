# Phase 11: Deep-User Workflow And Scope Regression - Research

**Researched:** 2026-04-17  
**Domain:** Python/FastAPI API-first regression stories for memory, fact lifecycle, task lifecycle, and fail-closed scope boundaries [VERIFIED: codebase grep]  
**Confidence:** HIGH

## User Constraints

- Phase 11 must satisfy `E2E-01`, `E2E-02`, `E2E-03`, `AUTH-01`, `AUTH-02`, `UNIT-01`, and `UNIT-02`, and it depends on the hardened Phase 10 test foundation. [VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/REQUIREMENTS.md]
- The phase goal is not broader browser E2E, worker-orchestration recovery, or adapter-matrix expansion. It is named API-first deep-user regression confidence plus focused unit seams. [VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md]
- Planning should verify the shipped `project_id`-centric system fail-closed today, while also aligning helper seams and future tests to the approved target scope model in `11-SCOPE-MODEL.md`. [VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md]
- Retrieval quality priorities from discuss are: missed recall first, wrong ranking second, misleading explanation third, and scope leakage as a separate dedicated track. [VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-DISCUSSION-LOG.md]

## Summary

The repo already has the right raw ingredients for Phase 11, but they are spread across baseline tests instead of being organized as named user stories. `tests/test_backend_baseline.py` already proves long-term supersede and conflict-review behavior, task normalization and cleanup side effects, and a wide set of API surfaces. `tests/test_identity_e2e.py` and `tests/test_identity_unit.py` already prove the start of a fail-closed project-scope matrix. [VERIFIED: tests/test_backend_baseline.py][VERIFIED: tests/test_identity_e2e.py][VERIFIED: tests/test_identity_unit.py]

The best Phase 11 shape is to regroup that existing coverage into three maintainer-readable story tracks plus one focused helper/rule track: memory and fact workflows, task handoff and cleanup workflows, auth-and-scope regression flows, and pure-unit rule seams. This keeps the phase API-first, readable, and debuggable without jumping ahead into Phase 12 orchestration work. [VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md]

The current search stack already exposes more explainability than the tests use today. `hybrid_search()` classifies query intent, reranks results with category/domain/focus bonuses, and `finalize_search_result()` already emits an `explainability` payload containing matched fields, matched terms, fact status, and lifecycle metadata. [VERIFIED: backend/main.py] That means Phase 11 does not need a large search rewrite to start proving explanation quality; it should first add story-level assertions over the real ranking reasons, and only add a thin explanation helper if the current payload is too raw for stable named-story assertions. [VERIFIED: backend/main.py][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md]

The strongest unit seams are already visible:

- `backend/governance/task_policy.py` owns task kind classification, materialization suppression, and task-memory filtering. [VERIFIED: backend/governance/task_policy.py]
- `backend/main.py` owns project enforcement (`enforce_project_identity`, `merge_project_id_into_metadata`, `merge_project_id_into_filters`, `ensure_memory_item_access`, `ensure_task_row_access`) and fact lifecycle transitions (`fact_action`, `fact_status`, history filtering). [VERIFIED: backend/main.py]

Those seams are exactly where Phase 11 should localize regressions rather than relying only on big API scenarios. The approved scope-model discussion also justifies adding pure helper coverage for future legacy-record classification into `user_global`, `project`, or `migration_review`, but this should stay helper-first rather than forcing a full contract migration inside this phase. [VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md]

**Primary recommendation:** Split Phase 11 into four plans: named memory/fact stories, named task/handoff/cleanup stories, fail-closed auth/scope matrix expansion, and focused fact/scope/helper backfill aligned to the approved target model without overreaching into full API migration. [VERIFIED: codebase grep][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md]

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| E2E-01 | Maintainer can verify a deep-user workflow from memory/task submission through retrieval and observable state changes using named scenarios. | Build dedicated scenario modules instead of hiding stories inside `test_backend_baseline.py`; keep them API-first with `TestClient` and isolated temp state. [VERIFIED: tests/conftest.py][VERIFIED: tests/test_backend_baseline.py] |
| E2E-02 | Maintainer can verify temporal fact supersede and conflict-review flows through real API scenarios. | Reuse the existing supersede and conflict-review surfaces, but regroup assertions so each named story verifies write response, list state, search state, and history visibility together. [VERIFIED: tests/test_backend_baseline.py][VERIFIED: backend/main.py] |
| E2E-03 | Maintainer can verify task lifecycle workflows, including materialization, follow-up retrieval, and cleanup side effects. | Extend the existing `/task-summaries`, `/tasks`, `/tasks/normalize`, `/tasks/{task_id}/close`, and `/tasks/{task_id}/archive` flows into multi-hop handoff and cleanup stories. [VERIFIED: tests/test_backend_baseline.py][VERIFIED: backend/main.py] |
| AUTH-01 | Maintainer can verify cross-scope authorization behavior across memory, task, search, close, archive, and forget actions. | Expand `tests/test_identity_e2e.py` into a complete surface matrix asserting `400`, `403`, and `404` semantics for explicit scope violations and hidden-resource behavior. [VERIFIED: tests/test_identity_e2e.py][VERIFIED: backend/main.py] |
| AUTH-02 | Maintainer can verify single-project, multi-project, and admin access paths through end-to-end tests that catch scope leakage. | Reuse scoped key creation plus admin baseline coverage to compare single-project defaults, multi-project explicit selection, and admin bypass across the same story surfaces. [VERIFIED: tests/test_identity_e2e.py][VERIFIED: backend/main.py] |
| UNIT-01 | Maintainer can verify task classification, cleanup heuristics, and non-work suppression with direct unit tests. | Add or deepen direct tests around `classify_task_kind`, `should_materialize_task`, `should_store_task_memory`, and cleanup heuristics so meta/system/snapshot/work decisions fail locally. [VERIFIED: backend/governance/task_policy.py][VERIFIED: tests/test_task_governance_targets.py] |
| UNIT-02 | Maintainer can verify project-scope enforcement, fact lifecycle transitions, and queue-state helpers with focused unit tests. | Extend identity helper tests, add fact-transition helper coverage, and add pure helper coverage for approved future scope classification logic where it clarifies migrations without dragging in Phase 12 orchestration. [VERIFIED: tests/test_identity_unit.py][VERIFIED: backend/main.py][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md] |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Named memory/fact stories | API / Backend | Search / Storage | These flows are expressed through `/memories`, `/search`, and cached fact state, not through runtime workers. [VERIFIED: backend/main.py][VERIFIED: tests/test_backend_baseline.py] |
| Multi-hop task handoff and cleanup stories | API / Backend | Governance rules | Materialization, retrieval, and normalization are all observable via public API endpoints, while classification logic lives in task-policy helpers. [VERIFIED: backend/main.py][VERIFIED: backend/governance/task_policy.py] |
| Fail-closed scope matrix | API / Backend | Storage / Audit | The main behavior is enforced in API-key verification plus project helper functions, then reflected in memory/task access and hidden-resource responses. [VERIFIED: backend/main.py][VERIFIED: tests/test_identity_e2e.py] |
| Focused helper backfill | Governance rules | API / Backend | Phase 11’s fastest regression localization lives in pure helper tests for task policy, fact transitions, and scope decisions. [VERIFIED: backend/governance/task_policy.py][VERIFIED: tests/test_identity_unit.py] |

## Standard Stack

### Core

| Library | Repo Version | Purpose | Why Standard |
|---------|--------------|---------|--------------|
| `pytest` | `8.4.2` in repo lockfile | Fast deterministic scenario and unit testing | All backend regression coverage already uses pytest fixtures and marker governance from Phase 10. [VERIFIED: pyproject.toml][VERIFIED: uv.lock] |
| `fastapi.testclient.TestClient` | existing repo base | API-first scenario execution with real lifespan | Phase 11 is intentionally API-first and does not require live runtime entrypoints by default. [VERIFIED: tests/conftest.py][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md] |
| Shared `FakeMemory` + temp SQLite harness | existing Phase 10 base | Isolated backend state across tests | The hardened test foundation from Phase 10 is already sufficient for this phase’s fast-lane stories. [VERIFIED: tests/conftest.py][VERIFIED: tests/support/fake_memory.py][VERIFIED: .planning/phases/10-test-harness-and-lane-foundation/10-04-SUMMARY.md] |

### Optional

| Tool | When to Use | Why Not Default |
|------|-------------|-----------------|
| `tests/support/live_backend.py` | Only if a story genuinely needs real HTTP process behavior | Phase 11’s main scope is API-first story depth, not process orchestration; Phase 12 owns deeper runtime coverage. [VERIFIED: tests/support/live_backend.py][VERIFIED: .planning/ROADMAP.md] |

## Code Anchors

- `backend/main.py:2569-2619` — current project enforcement and hidden-resource helpers. [VERIFIED: backend/main.py]
- `backend/main.py:773-910` — fact lifecycle responses surface `fact_action` and `fact_status`. [VERIFIED: backend/main.py]
- `backend/main.py:2994-3345` — search-result explainability, reranking, lexical fallback, and task-aware search joins. [VERIFIED: backend/main.py]
- `backend/governance/task_policy.py` — task-kind classification, materialization, and task-memory suppression. [VERIFIED: backend/governance/task_policy.py]
- `tests/test_backend_baseline.py:140-241` — current fact supersede and conflict-review regression anchors. [VERIFIED: tests/test_backend_baseline.py]
- `tests/test_backend_baseline.py:1237-1435` — current task normalize/archive/prune anchors. [VERIFIED: tests/test_backend_baseline.py]
- `tests/test_identity_e2e.py` — current end-to-end project-scope matrix anchors. [VERIFIED: tests/test_identity_e2e.py]
- `tests/test_identity_unit.py` — current helper-level project enforcement anchors. [VERIFIED: tests/test_identity_unit.py]

## Architecture Patterns

### Pattern 1: Named API-First Scenario Modules

**What:** Move deep-user workflows out of generic baseline files into dedicated scenario modules with story-shaped test names.

**When to use:** Use for memory/fact flows and task/handoff/cleanup flows that should read like a regression story rather than a helper audit.

**How here:** Create dedicated files such as `tests/test_deep_user_memory_flows.py` and `tests/test_deep_user_task_flows.py`, while reusing existing helper fixtures and minimal setup from `tests/conftest.py`. [VERIFIED: tests/conftest.py][VERIFIED: tests/test_backend_baseline.py]

### Pattern 2: Dual-Surface Fact Assertions

**What:** Each fact story should assert both the write-side decision and the retrieval-side state model.

**When to use:** Use for supersede and conflict-review flows.

**How here:** Assert the POST `/memories` response (`fact_action`, `fact_status`, supersede/conflict IDs), then assert `/memories` list state plus `/search` with and without `include_history`. [VERIFIED: tests/test_backend_baseline.py][VERIFIED: backend/main.py]

### Pattern 3: Multi-Hop Task Continuity Stories

**What:** A good task story should prove that handoff information survives at least one continuation hop, not just that a single summary was stored.

**When to use:** Use for `E2E-03` and for the discuss-approved “next action + current state + task identity” continuity standard.

**How here:** Chain `/task-summaries` -> `/tasks` / `/search` -> follow-up `/task-summaries` -> `/tasks/normalize` assertions, with task identity and cleanup side effects visible at each step. [VERIFIED: backend/main.py][VERIFIED: tests/test_backend_baseline.py][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-DISCUSSION-LOG.md]

### Pattern 4: Fail-Closed Matrix Expansion

**What:** Reuse scoped key creation but cover every relevant surface instead of one or two representative calls.

**When to use:** Use for AUTH requirements.

**How here:** Keep the current `create_project_key()` style in `tests/test_identity_e2e.py`, then expand across memory creation/search/read/delete plus task create/list/read/close/archive and admin comparisons. Preserve endpoint-faithful `400`/`403`/`404` semantics instead of flattening everything to one status code. [VERIFIED: tests/test_identity_e2e.py][VERIFIED: backend/main.py]

### Pattern 5: Focused Rule Seams Before Large Refactors

**What:** Add or extract pure helpers where Phase 11 needs stable regression localization, but do not perform broad architecture migration inside the test phase.

**When to use:** Use for task policy edge cases, fact transition decisions, and approved future scope-classification logic.

**How here:** Keep new helpers narrowly scoped to decisions that Phase 11 must verify, such as legacy-record classification into `user_global`, `project`, or `migration_review`, and explanation-role selection for mixed retrieval. [VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md][VERIFIED: backend/governance/task_policy.py]

### Pattern 6: Thin Explanation Layer Over Real Ranking Signals

**What:** If story-level assertions need something more human-readable than `explainability`, add only a thin explanation helper that uses real reranking signals.

**When to use:** Use only if current explainability fields are too raw to express the approved “short natural-language explanation with evidence” standard.

**How here:** Build explanations from existing query intent, matched fields, fact status, and winner signals. Do not invent a second ranking system just for explanation text. [VERIFIED: backend/main.py][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-DISCUSSION-LOG.md]

## Anti-Patterns To Avoid

- **Do not keep Phase 11 hidden inside `tests/test_backend_baseline.py`:** that makes story intent hard to scan and weakens regression readability. [VERIFIED: tests/test_backend_baseline.py]
- **Do not drag worker/scheduler process coverage into this phase by default:** real runtime orchestration belongs to Phase 12 unless a story absolutely cannot be expressed through `TestClient`. [VERIFIED: .planning/ROADMAP.md]
- **Do not “solve” scope planning by immediately migrating the public API contract:** Phase 11 should prepare helper seams and regression confidence, not bundle the entire scope-model cutover. [VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md]
- **Do not add fabricated explanation text:** any explanation layer added here must be grounded in the actual ranking reasons already present in search logic. [VERIFIED: backend/main.py][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-DISCUSSION-LOG.md]
- **Do not rely only on large API stories for rule regressions:** task policy and scope/fact helpers need direct unit coverage so failures localize quickly. [VERIFIED: backend/governance/task_policy.py][VERIFIED: tests/test_identity_unit.py]

## Recommended Phase Split

1. Named memory and fact workflows
2. Named task handoff and cleanup workflows
3. Fail-closed authorization and scope matrix
4. Focused unit seams for task policy, fact transitions, and scope-model preparation

This split matches the requirements, the existing code seams, and the discuss-approved scope direction without smearing everything into one oversized regression file. [VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md]
