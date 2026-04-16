# automem

## What This Is

automem is a shared memory and task-governance backend for multi-agent workflows. It gives Codex, Claude Code, OpenClaw, OpenCode, and similar clients one governed memory plane for durable recall, task state, consolidation, and policy enforcement.

The product is not just a memory store. It is a control plane that decides what should be remembered, what should be dropped, how task state should be materialized, and how shared access boundaries should be enforced across agents and projects.

## Core Value

Turn noisy agent output into trustworthy shared memory and task state that multiple agents can reuse safely.

## Current State

- `v1.0` shipped on `2026-04-16`.
- The backend now fails closed by default, binds non-admin keys to real identities, and centralizes governance decisions on the server side.
- Retrieval, fact lifecycle, and runtime architecture upgrades are live, including explainable hybrid search and the API/worker/MCP split.
- Foundational verification and milestone-wide Nyquist validation are complete for Phase `01-07`.
- The current planning state has moved into milestone `v1.1`, which focuses on turning validated behavior claims into durable regression protection through deeper end-to-end and unit test coverage.

## Requirements

### Validated

- [x] Backend-owned memory governance with hybrid filtering and task admission control — `v1.0`
- [x] Shared API surface for memory, task state, consolidation, audit, and MCP-facing adapters — `v1.0`
- [x] Foundational auth hardening, task normalization, and scheduled consolidation safety — `v1.0`
- [x] Shared identity and access model beyond raw `user_id` — `v1.0`
- [x] Retrieval and explainability upgrades for memory/task recall — `v1.0`
- [x] Temporal fact lifecycle and conflict governance — `v1.0`
- [x] Runtime split between hot-path admission and background governance workers — `v1.0`
- [x] Foundational verification evidence chain for auth, governance, and consolidation — `v1.0`
- [x] Milestone-wide validation baseline and Nyquist coverage for completed product phases — `v1.0`

### Active

- [ ] Build a realistic end-to-end regression suite from a deep-user perspective across API, worker, scheduler, search, and task flows
- [ ] Backfill high-value unit coverage for core rules, edge conditions, and failure-recovery behavior
- [ ] Prove real behavior with executable tests so capability claims stay grounded in observable outcomes

### Out of Scope

- End-user chat UI product — current focus is the backend/control-plane layer
- Fully generic organization-wide RBAC from day one — phased rollout is safer than premature over-modeling
- Replacing upstream agent runtimes — automem integrates with them rather than becoming a new agent shell

## Current Milestone: v1.1 Testing Depth & Real-World Regression

**Goal:** Upgrade the test system from isolated capability checks into realistic workflow regression protection that demonstrates how automem behaves in practice.

**Target features:**
- High-value end-to-end scenarios that reflect deep-user behavior instead of only endpoint-by-endpoint validation
- Unit coverage for core rules, permissions, edge cases, and failure-recovery paths
- Test evidence that turns functional claims into continuously verified reality

## Context

- The current codebase supports multiple adapters and a shared backend contract.
- v1.0 execution history is archived under [.planning/milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md).
- Existing tests cover governance, identity enforcement, scheduled consolidation, and the governance worker runtime split.

## Constraints

- **Compatibility**: Existing adapters and MCP integrations must keep working while the backend evolves.
- **Safety**: Shared memory cannot regress to fail-open identity or cross-project leakage.
- **Incremental delivery**: Major upgrades should continue landing phase-by-phase with tests first, not as a big-bang rewrite.
- **Operational simplicity**: The system should remain deployable in self-hosted environments with cron/systemd style automation.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Backend owns memory governance | Prevent adapter drift and inconsistent memory quality | ✓ Good |
| Optimization work is organized as phases | Keeps product evolution incremental and reviewable | ✓ Good |
| Shared identity starts at project scope before team/org scope | Smallest useful step that unlocks safe collaboration | ✓ Good |
| Tests should lead phase execution | Protects a sensitive backend where regressions are hard to notice manually | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone**:
1. Full review of all sections
2. Core Value check - still the right priority?
3. Audit Out of Scope - reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-16 after starting milestone v1.1*
