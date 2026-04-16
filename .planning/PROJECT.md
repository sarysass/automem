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
- [x] Retrieval and explainability upgrades for memory/task recall (validated in Phase 05: hybrid retrieval now returns explainable match paths, metadata filters, and task alias recall)
- [x] Temporal fact lifecycle and conflict governance (validated in Phase 06: long-term memory now carries lifecycle metadata, supersede chains, conflict-review state, and history-aware retrieval)
- [x] Runtime split between hot-path admission and background governance workers (validated in Phase 07: governance jobs, worker entrypoint, runtime topology, and API/worker/MCP role separation are live)
- [x] Foundational verification evidence chain for auth, governance, and consolidation (validated in Phase 08: Phase 01-03 now each have explicit `VERIFICATION.md`, and milestone traceability points to those artifacts)
- [x] Milestone-wide validation baseline and Nyquist coverage for Phase 01-07 (validated in Phase 09: every completed product phase now has a compliant `*-VALIDATION.md` artifact and the milestone audit no longer reports validation gaps)

### Active

None — v1.0 validated scope is complete and ready for milestone close-out.

### Out of Scope

- End-user chat UI product — current focus is the backend/control-plane layer
- Fully generic organization-wide RBAC from day one — phased rollout is safer than premature over-modeling
- Replacing upstream agent runtimes — automem integrates with them rather than becoming a new agent shell

## Context

- The current codebase already supports multiple adapters and a shared backend contract.
- The project has completed product phases `04-07` and the milestone-close phases `08-09`.
- Codebase analysis has already identified the major concerns: identity boundaries, governance consistency, retrieval quality, fact lifecycle, and runtime architecture.
- Existing tests already cover memory governance, task normalization, scheduled consolidation, and the first wave of project-scoped identity behavior.
- Recent open-source research has been distilled into eight product upgrades that map to phases `04-07`, followed by gap-closure phases that restored verification and validation hygiene before milestone archival.

## Current State

- Phase `04` is complete: project-scoped identity enforcement now covers memory/task writes, reads, and memory deletion, and the CLI can mint bound keys with `user_id` plus repeated `project_id` scopes.
- Phase `05` is complete: search now exposes explainable hybrid retrieval signals (`semantic` / `lexical` / `metadata`), carries lifecycle status in results, and can recover task memories via task title and alias metadata.
- Phase `06` is complete: long-term memory now behaves like versioned facts with lifecycle metadata, supersede chains, conflict-review states, and history-aware retrieval.
- Phase `07` is complete: heavy governance work now runs through background jobs and a governance worker, while runtime topology and docs expose the API/worker/MCP split.
- Phase `08` is complete: foundational auth/governance/consolidation phases now have explicit verification artifacts, `REQUIREMENTS.md` is back to `13/13 satisfied`, and orphaned requirement debt is closed.
- Phase `09` is complete: Phase `01-07` now all have compliant `*-VALIDATION.md` artifacts, and `v1.0-MILESTONE-AUDIT.md` now passes.
- The project is ready for milestone close-out rather than additional v1.0 scope expansion.

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
*Last updated: 2026-04-16 after Phase 09 execution*
