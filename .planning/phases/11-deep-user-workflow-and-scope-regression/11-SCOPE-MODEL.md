# Phase 11 Scope Model Decision

**Date:** 2026-04-17
**Status:** Approved for planning and implementation prep
**Phase:** 11-deep-user-workflow-and-scope-regression

## Why This Exists

The current access model mixes multiple concerns in one surface:

- API key scopes decide capability
- non-admin keys also bind a `user_id`
- `project_id` currently acts as both a visibility boundary and an implicit memory scope
- `task_id` and `run_id` organize memory, but can also look like access layers

This creates too much ambiguity. In particular, `project_id = null` currently overloads two meanings:

- this memory is intentionally global to the user
- this memory was written without enough scope information

Phase 11 should test the fail-closed behavior of the shipped system, but downstream planning should already align to the target scope model we want to move toward.

## Approved Model

### 1. Main visibility scopes

Only two primary memory scopes remain in the target model:

- `user_global`
- `project`

`task` is **not** a third access scope. It remains an organization dimension layered on top of one of the two primary scopes.

### 2. Authentication and identity

- API keys continue to own capability via `scopes`
- non-admin keys remain bound to a single effective `user`
- `agent_id` is retained for attribution and audit, not as a primary access boundary

### 3. Scope shape

The system should move to an explicit nested scope object instead of inferring meaning from `project_id`.

Examples:

```json
{ "scope": { "type": "user_global" } }
```

```json
{ "scope": { "type": "project", "id": "project-alpha" } }
```

### 4. Query inheritance

Project-context queries should inherit user-global context by default.

Default project query behavior:

- search `project` memories first
- also include `user_global` memories for shared identity, preference, project-index, and stable-constraint context

Strict project-only mode is allowed, but it must be triggered by an explicit request parameter rather than implicit behavior.

### 5. Ambiguous write behavior

When scope is unclear, the system should not silently guess.

Approved behavior:

- if the caller is operating in a single-project context, the backend may infer that project scope
- otherwise, ambiguous writes must require explicit `scope`

This rule applies especially to current-state statements such as:

- current focus
- current workflow
- what we are mainly working on now

These are high-ambiguity inputs and should not be auto-scoped without stronger evidence.

## What Belongs Where

### `user_global`

Use `user_global` for information that should travel with the same user across multiple projects by default.

Typical examples:

- user profile facts
- communication and output preferences
- stable collaboration preferences
- cross-project reusable knowledge
- project index cards
- project identification and stable constraints
- long-lived boundaries and durable decisions that are useful across projects

### `project`

Use `project` scope for information that is valid only inside a specific project workspace, or would pollute retrieval elsewhere.

Typical examples:

- detailed project state
- project-specific progress
- handoff memory
- blockers
- next actions
- dynamic project facts
- project-local operational decisions

### Project overview split

Project overview content is intentionally split across both scopes:

- brief overview, project map, stable constraints -> `user_global`
- detailed status, current execution state -> `project`

This keeps cross-project recall useful without letting operational noise leak everywhere.

## Retrieval and Explanation Rules

### Main retrieval policy

Mixed retrieval should use **query-intent-based bias**, not a fixed “project always wins” rule.

Bias toward `user_global` when the query is mainly about:

- identity
- preferences
- project overview
- stable constraints

Bias toward `project` when the query is mainly about:

- current project status
- next step
- blocker
- handoff
- project execution state

### Mixed query behavior

When a query genuinely spans both scopes:

- choose the main answer from the dominant intent
- keep the other scope as supporting context

This is a “main answer + supporting context” pattern, not a hard merge where one side disappears.

### Explanation policy

For mixed queries, explanations should describe the role of each source rather than exposing internal scope terms directly.

Preferred style:

- “the main answer comes from current project state”
- “supporting context comes from cross-project preferences and stable constraints”

Avoid exposing raw internal framing such as `project_scoped` or `user_global` in user-facing explanations by default.

## Migration Direction

The target migration is a clean cut, not long-term dual semantics.

Approved direction:

- move API contracts to explicit `scope`
- move internal models to explicit `scope`
- migrate stored records to the new representation
- do not preserve `project_id` as the long-term semantic source of truth

### Migration strategy

Migration should be mostly automatic, with a narrow review bucket for truly ambiguous cases.

#### Strong `project` evidence

- explicit `project_id`
- `task_id` or `run_id`
- `task`-domain memory such as `handoff`, `progress`, `blocker`, `next_action`
- `project_context` content that is clearly about current state
- records that cluster strongly around the same project

#### Strong `user_global` evidence

- `user_profile` or `preference`
- stable facts without task/project binding
- project overview content
- content with clear cross-project reuse value
- content that reads like an index/map rather than current status

#### Conflict handling

When evidence points both ways, resolve by evidence strength:

- hard structural evidence wins over semantic hints
- semantic hints win over weak helper signals

#### Review bucket

If neither side has enough evidence, place the record into `migration_review` instead of forcing a guess.

## Planning Implications For Phase 11

Phase 11 should not pretend the current `project_id`-centric shape is the long-term model. Planning should instead prepare tests and implementation work around these questions:

- fail-closed behavior while the old model still exists
- correct future behavior for `user_global` plus `project` inheritance
- mixed-query ranking and explanation quality across both scopes
- migration safety for legacy records

## Open Implementation Questions

These are intentionally left for planning and execution, not frozen here:

- exact request and response schema changes
- whether strict mode is a boolean or a small retrieval-mode enum
- how `migration_review` is stored and surfaced operationally
- whether retrieval APIs expose role-oriented explanation fields, natural-language explanations, or both
