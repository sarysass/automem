# Phase 11: Deep-User Workflow And Scope Regression - Pattern Map

**Mapped:** 2026-04-17  
**Files analyzed:** 9  
**Analogs found:** 8 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `tests/test_deep_user_memory_flows.py` | test | request-response | `tests/test_backend_baseline.py` | role-match |
| `tests/test_deep_user_task_flows.py` | test | request-response | `tests/test_backend_baseline.py` | role-match |
| `tests/test_identity_e2e.py` | test | request-response | `tests/test_identity_e2e.py` | exact |
| `tests/test_identity_unit.py` | test | transform | `tests/test_identity_unit.py` | exact |
| `tests/test_scope_model_unit.py` | test | transform | `tests/test_identity_unit.py` | partial |
| `tests/test_task_governance_targets.py` | test | transform | `tests/test_task_governance_targets.py` | exact |
| `backend/main.py` | backend | request-response | `backend/main.py` | exact |
| `backend/governance/task_policy.py` | backend | transform | `backend/governance/task_policy.py` | exact |
| `.planning/phases/11-deep-user-workflow-and-scope-regression/11-SCOPE-MODEL.md` | doc | transform | `.planning/phases/11-deep-user-workflow-and-scope-regression/11-CONTEXT.md` | partial |

## Pattern Assignments

### `tests/test_deep_user_memory_flows.py`

**Analog:** `tests/test_backend_baseline.py`

Use the current POST `/memories` -> GET `/memories` -> POST `/search` progression as the main structure, but rename tests so the workflow reads like a regression story instead of a helper audit.

Key reusable anchors:

- fact supersede flow in `tests/test_backend_baseline.py:140-193`
- conflict-review flow in `tests/test_backend_baseline.py:196-241`

Expected shape:

```python
def test_preference_intent_query_recalls_current_fact_with_history_trace(...):
    ...

def test_project_fact_conflict_stays_active_until_review(...):
    ...
```

Keep API setup explicit and scenario-local. Do not hide the story behind generic helper wrappers.

---

### `tests/test_deep_user_task_flows.py`

**Primary analog:** `tests/test_backend_baseline.py`

Use the current task-summary and normalize flows as the backbone, but group them into multi-hop handoff and cleanup stories.

Key reusable anchors:

- title rewrite and summary preview flow in `tests/test_backend_baseline.py:1204-1234`
- normalize/archive/prune flows in `tests/test_backend_baseline.py:1237-1435`

Expected shape:

```python
def test_multi_hop_handoff_keeps_task_identity_next_action_and_progress(...):
    ...

def test_cleanup_archives_noise_without_hiding_real_work(...):
    ...
```

Prefer a single story to cross `/task-summaries`, `/tasks`, `/search`, and `/tasks/normalize` rather than proving each endpoint in isolation.

---

### `tests/test_identity_e2e.py`

**Analog:** `tests/test_identity_e2e.py`

Keep the file’s existing scoped-key fixture style and expand the surface matrix in place.

Reusable pattern:

```python
def create_project_key(...):
    response = client.post("/agent-keys", ...)
    assert response.status_code == 200
    return response.json()["token"]
```

Use the current exact style for:

- single-project defaulting
- multi-project explicit-project requirements
- hidden-resource `404`
- conflicting project filter rejection

Do not create a parallel auth helper unless the current file becomes unmanageably large.

---

### `tests/test_identity_unit.py`

**Analog:** `tests/test_identity_unit.py`

Keep pure helper tests short and direct. Current pattern:

```python
with pytest.raises(HTTPException, match="project_id is required"):
    backend_module.enforce_project_identity(auth, None)
```

Extend in the same style for:

- admin bypass cases
- empty/normalized project scopes
- direct access helpers (`ensure_memory_item_access`, `ensure_task_row_access`) where pure setup is tractable

---

### `tests/test_scope_model_unit.py`

**Primary analog:** `tests/test_identity_unit.py`

If Phase 11 introduces pure helper seams for legacy-record scope classification or mixed-retrieval role selection, keep them in a new small unit file rather than crowding `tests/test_identity_unit.py`.

Pattern to follow:

```python
def test_classify_legacy_record_routes_to_project_when_task_and_project_signals_are_present(...):
    ...

def test_classify_legacy_record_routes_to_migration_review_when_evidence_is_weak(...):
    ...
```

This file should stay pure and fast. No `TestClient` here.

---

### `tests/test_task_governance_targets.py`

**Analog:** `tests/test_task_governance_targets.py`

Keep the current edge-case style for task policy and cleanup heuristics, and extend it instead of duplicating classification coverage elsewhere.

Best fit additions:

- conversational/meta versus work boundary cases
- system-noise suppression cases
- materialization/no-materialization edge cases

---

### `backend/main.py`

**Analog:** `backend/main.py`

Keep new helpers adjacent to the surfaces they support instead of scattering them into many new modules during this test-focused phase.

Likely touch points:

- search result finalization and optional explanation helper
- fact lifecycle helper extraction if needed for stable unit coverage
- current scope enforcement helpers
- optional pure helper seams for future scope classification

Do not mix a full API schema migration into this phase’s changes unless a task explicitly calls for it.

---

### `backend/governance/task_policy.py`

**Analog:** `backend/governance/task_policy.py`

Preserve the current compact pure-function style:

```python
def should_materialize_task(...):
    ...
```

If rules change, adjust them incrementally and keep tests directly tied to the new branches.

## Pattern Notes

- Prefer adding new story files for readability rather than endlessly extending `tests/test_backend_baseline.py`.
- Prefer extending `tests/test_identity_e2e.py` and `tests/test_identity_unit.py` in place for auth/scope work so current coverage stays centralized.
- Any future-scope helper added in Phase 11 should be pure, testable, and narrowly scoped to classification or explanation-role selection.
