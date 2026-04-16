# Phase 11: Deep-User Workflow And Scope Regression - Context

**Gathered:** 2026-04-17
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase proves the shipped backend through named API-first regression stories and focused unit backfill. The scope is limited to deep user workflows around memory, fact lifecycle, task lifecycle, and fail-closed authorization boundaries. It does not expand into browser E2E, broad adapter-matrix testing, or production refactors.

</domain>

<decisions>
## Implementation Decisions

### Scenario portfolio
- **D-01:** Phase 11 should be organized around named user stories, not endpoint-by-endpoint coverage. Each primary scenario should cross multiple API surfaces and end with observable state assertions.
- **D-02:** The scenario portfolio should prioritize four story families: memory or task submission through retrieval and visible state change, temporal fact supersede behavior, temporal fact conflict-review behavior, and task lifecycle behavior including materialization, follow-up retrieval, and cleanup side effects.
- **D-03:** These stories should stay API-first and maintainer-oriented. Prefer deterministic FastAPI test flows first, then reuse the Phase 10 live harness only when a scenario genuinely needs real HTTP or runtime-process behavior.

### Authorization and scope matrix
- **D-04:** Phase 11 should test fail-closed scope behavior against the current shipped system, but planning should treat the approved target model as two primary scopes only: `user_global` and `project`. `task` remains an organization dimension, not a third access boundary.
- **D-05:** Retrieval behavior should evolve toward project queries inheriting `user_global` by default, with an explicit strict-project parameter available when callers want project-only results.
- **D-06:** Non-admin writes should not silently guess scope except in a single-project context. High-ambiguity “current state” inputs should require stronger evidence or explicit scope.
- **D-07:** `agent_id` should continue as attribution and audit context, not as the primary isolation layer. Scope enforcement should center on user identity plus explicit memory scope.
- **D-08:** Hidden-resource behavior should remain endpoint-faithful. Cross-project reads and lifecycle actions should continue to assert protected outcomes such as `404` for inaccessible resources and `400`/`403` for explicit scope violations.

### Fact and task lifecycle evidence
- **D-09:** Fact lifecycle coverage should validate both the write-side response payload and the retrieval-side state model. Supersede scenarios should assert `fact_action`, `fact_status`, history visibility, and the active-versus-superseded search behavior together.
- **D-10:** Conflict-review scenarios should prove that a new conflicting fact is retained for review without displacing the active fact, and that history-aware retrieval exposes the review record correctly.
- **D-11:** Task lifecycle scenarios should validate materialization, retrieval, close/archive transitions, and cleanup/normalization side effects as one coherent workflow instead of isolated helper-only assertions.

### Unit backfill strategy
- **D-12:** Focused unit backfill should target stable rule and helper seams rather than re-testing whole API stories. The primary targets are task classification and suppression rules, cleanup heuristics, current project-scope enforcement helpers, fact lifecycle helper functions, and future scope-migration decision logic.
- **D-13:** Unit coverage should localize regressions in `backend/governance/task_policy.py` and the scope/fact helper functions in `backend/main.py`, especially the helpers that currently normalize `project_id` and the future helpers that classify legacy records into `user_global`, `project`, or `migration_review`.
- **D-14:** Queue, worker, and scheduler job-state helpers should only be covered here when they support Phase 11 scope-local assertions; deeper orchestration and failure-path behavior remains reserved for Phase 12.

### the agent's Discretion
- Exact scenario names, fixture helper names, and file splits across the new test modules
- Whether a specific regression is clearer as a parametrized matrix or as separate named tests
- Minor test data strings, IDs, and summary wording as long as they keep the intent of the named stories clear

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and phase scope
- `.planning/ROADMAP.md` — v1.1 milestone framing, Phase 11 goal, dependency on Phase 10, and success criteria for deep-user workflow and scope regression
- `.planning/PROJECT.md` — current product state, milestone intent, and constraints that keep this phase focused on regression confidence rather than refactoring

### Acceptance boundaries
- `.planning/REQUIREMENTS.md` — `E2E-01`, `E2E-02`, `E2E-03`, `AUTH-01`, `AUTH-02`, `UNIT-01`, and `UNIT-02`, plus the v1.1 out-of-scope section

### Approved scope direction
- `.planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md` — approved target scope model, retrieval inheritance rules, migration direction, and ambiguity handling to use during planning

### Inherited test foundation
- `.planning/phases/10-test-harness-and-lane-foundation/10-VALIDATION.md` — inherited validation contract for the shared harness and lane structure this phase builds on
- `.planning/phases/10-test-harness-and-lane-foundation/10-04-SUMMARY.md` — hardening decisions around sentinel payloads, strict shared test semantics, and durable runtime-driver contracts

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/conftest.py`: fast-lane baseline with `TestClient`, isolated temp databases, and `FakeMemory`
- `tests/support/live_backend.py`: shared live-process harness from Phase 10 for scenarios that truly need real HTTP
- `tests/support/runtime_drivers.py`: stable runtime subprocess helpers if a scenario must cross into script-driven behavior
- `tests/test_identity_e2e.py`: existing API-key creation and project-scope matrix patterns that can be expanded instead of reinvented
- `tests/test_backend_baseline.py`: existing fact lifecycle, task normalization, pagination, and retrieval assertions that can be regrouped into named deep-user scenarios

### Established Patterns
- Authentication and tenant enforcement are centralized in `backend/main.py` via API-key verification plus `enforce_project_identity`, `merge_project_id_into_metadata`, and `merge_project_id_into_filters`
- Fact lifecycle is modeled as active, superseded, and conflict-review records, with search behavior changing based on `include_history`
- Task governance distinguishes work, meta, system, and snapshot tasks in `backend/governance/task_policy.py`, and normalization/cleanup flows are exposed through API endpoints rather than hidden helpers
- Current regression coverage already mixes focused unit tests and API tests; Phase 11 should deepen that pattern rather than replace it
- The shipped code still uses `project_id` as the primary scope signal today; planning for Phase 11 should treat that as the current implementation shape to verify, not the final target semantics

### Integration Points
- Memory and fact stories connect through `/memories`, `/memories/{memory_id}`, and `/search`
- Task stories connect through `/task-summaries`, `/tasks`, `/tasks/{task_id}`, `/tasks/{task_id}/close`, `/tasks/{task_id}/archive`, and `/tasks/normalize`
- Scope-safety stories connect through `/agent-keys` plus the same memory and task surfaces under scoped non-admin keys
- Cleanup side-effect assertions can reuse `/consolidate` and `/tasks/normalize` where task-memory and archived-state behavior must be observed end to end

</code_context>

<specifics>
## Specific Ideas

- Scope direction is now guided by the approved Phase 11 scope decision rather than the shipped `project_id`-only semantics
- Retrieval quality should prioritize “should have found it but didn't” regressions first, ranking failures second, and explanation failures third
- Core-query explanations should be short natural-language explanations grounded in the real ranking reasons, not fabricated post-hoc justifications
- Mixed-scope retrieval should choose a main answer from query intent and preserve the other scope as supporting context
- Keep the stories maintainer-readable: scenario names should describe the workflow or boundary being protected, not the endpoint under test
- Prefer standard backend regression approaches already used in the repo; no additional product-style UX requirements were introduced here

</specifics>

<deferred>
## Deferred Ideas

- Full browser E2E expansion remains out of scope for this phase
- Broad adapter-fleet runtime coverage remains out of scope for this milestone slice
- Real-dependency contract lanes for mem0 or Qdrant remain future work beyond the default Phase 11 regression scope

</deferred>

---

*Phase: 11-deep-user-workflow-and-scope-regression*
*Context gathered: 2026-04-17*
