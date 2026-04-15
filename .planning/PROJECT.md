# automem

## What This Is

automem is a shared memory and task-governance backend for multi-agent workflows. It gives Codex, Claude Code, OpenClaw, OpenCode, and similar clients one governed memory plane for durable recall, task state, consolidation, and policy enforcement.

The product is not just a memory store. It is a control plane that decides what should be remembered, what should be dropped, how task state should be materialized, and how shared access boundaries should be enforced across agents and projects.

## Core Value

Turn noisy agent output into trustworthy shared memory and task state that multiple agents can reuse safely.

## Requirements

### Validated

- [x] Backend-owned memory governance with hybrid filtering and task admission control
- [x] Shared API surface for memory, task state, consolidation, audit, and MCP-facing adapters
- [x] Foundational auth hardening, task normalization, and scheduled consolidation safety
- [x] Shared identity and access model beyond raw `user_id` (validated in Phase 04: project-scoped enforcement across memory, task, and CLI key creation)

### Active

- [ ] Retrieval and explainability upgrades for memory/task recall
- [ ] Temporal fact lifecycle and conflict governance
- [ ] Runtime split between hot-path admission and background governance workers

### Out of Scope

- End-user chat UI product — current focus is the backend/control-plane layer
- Fully generic organization-wide RBAC from day one — phased rollout is safer than premature over-modeling
- Replacing upstream agent runtimes — automem integrates with them rather than becoming a new agent shell

## Context

- The current codebase already supports multiple adapters and a shared backend contract.
- The project recently moved from foundational hardening into optimization phases `04-07`.
- Codebase analysis has already identified the major concerns: identity boundaries, governance consistency, retrieval quality, fact lifecycle, and runtime architecture.
- Existing tests already cover memory governance, task normalization, scheduled consolidation, and the first wave of project-scoped identity behavior.
- Recent open-source research has been distilled into eight product upgrades that now map directly to phases `04-07`: permissions beyond `user_id`, deterministic governance surfaces, hybrid retrieval, explainable recall, temporal facts, conflict detection, hot/background runtime split, and API + worker + MCP control-plane shape.

## Current State

- Phase `04` is complete: project-scoped identity enforcement now covers memory/task writes, reads, and memory deletion, and the CLI can mint bound keys with `user_id` plus repeated `project_id` scopes.

## Constraints

- **Compatibility**: Existing adapters and MCP integrations must keep working while the backend evolves.
- **Safety**: Shared memory cannot regress to fail-open identity or cross-project leakage.
- **Incremental delivery**: Major upgrades need to land phase-by-phase with tests first, not as a big-bang rewrite.
- **Operational simplicity**: The system should remain deployable in self-hosted environments with cron/systemd style automation.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Backend owns memory governance | Prevent adapter drift and inconsistent memory quality | ✓ Good |
| Optimization work is organized as phases `04-07` | Keeps product evolution incremental and reviewable | ✓ Good |
| Shared identity starts at project scope before team/org scope | Smallest useful step that unlocks safe collaboration | ✓ Good |
| Tests should lead phase execution | Protects a sensitive backend where regressions are hard to notice manually | ✓ Good |

---
*Last updated: 2026-04-16 after Phase 04 execution*
