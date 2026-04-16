# Memory Governance Redesign Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Rebuild automem's memory ingestion and cleanup pipeline so noisy prompts, metadata, cron snapshots, and transient task chatter are rejected or compacted centrally instead of repeatedly leaking into long-term and task memory.

**Architecture:** Move memory quality decisions into the backend with a hybrid rules-plus-LLM governance layer. Adapters become thin collectors with only minimal local dedupe/noise checks. Online ingestion uses a small structured classifier/judge plus hard-rule fast paths; offline consolidation uses stronger semantic compaction and migration logic. Task summary storage must be gated by task kind and noise classification before any task memory is written.

**Tech Stack:** FastAPI, sqlite task registry, automem backend, existing adapter templates (Codex/OpenClaw/OpenCode/Claude Code), structured LLM classification via current backend LLM config, pytest.

---

## Problem Statement

The current design fails in three independent layers:

1. `memory-route` and long-term extraction are too permissive.
   Temporary prompts, time scaffolding, cron banners, and raw metadata can route into `long_term`.
2. `task-summaries` writes task memory before system/meta/noise gating.
   Cron snapshots and conversation metadata become durable task memory.
3. `/consolidate` is a narrow cleaner, not a full governance pipeline.
   It mostly canonicalizes `preference` and deletes a tiny set of task markers. It does not normalize tasks, does not compact semantic duplicates, and does not clean many historical noise families.

This creates a feedback loop:

- adapters auto-capture too aggressively
- backend stores noisy task summaries
- noisy task summaries enter later recall/matching
- later turns are biased by polluted history

## Design Principles

1. Backend owns meaning.
   Adapters should not decide what is durable memory beyond minimal local throttling.
2. Rules catch the obvious.
   Empty text, exact scaffold markers, exact transport metadata headers, and exact duplicate fingerprints should be filtered cheaply.
3. LLM handles ambiguous semantics.
   The model decides whether content is durable, task-progress, transient prompting, system metadata, or compactable duplicate.
4. Prefer false negatives over false positives.
   If uncertain, do not store.
5. Task table and task memory are different artifacts.
   System/meta tasks may exist in the registry for observability while writing zero task memory.

## Target End State

### Online Ingestion

- All writes flow through a backend governance layer before storage.
- `memory-route`, `/memories`, and `/task-summaries` share the same classification primitives.
- Adapters send raw candidate content plus context; backend decides `drop | long_term | task | mixed`.

### Offline Consolidation

- Daily maintenance performs:
  - memory noise sweep
  - semantic canonicalization and merge
  - task-kind normalization
  - cron/system snapshot pruning
  - optional cache rebuild for inferred blind spots

### Adapters

- OpenClaw/OpenCode/Claude Code stop acting like policy engines.
- They keep only:
  - capture trigger selection
  - per-session fingerprint dedupe
  - extremely obvious local skip patterns
- All semantic keep/drop routing moves server-side.

## Proposed Backend Modules

Create a new package, for example:

```text
backend/governance/
├── __init__.py
├── rules.py
├── judge.py
├── schemas.py
├── canonicalize.py
├── task_policy.py
└── consolidate.py
```

### `schemas.py`

Define structured governance outputs:

- `NoiseKind`
  - `empty`
  - `time_scaffold`
  - `cron_template`
  - `transport_metadata`
  - `system_prompt_scaffold`
  - `heartbeat_snapshot`
  - `transient_instruction`
  - `assistant_chatter`
- `MemoryKind`
  - `user_profile`
  - `preference`
  - `project_rule`
  - `project_context`
  - `architecture_decision`
  - `task_summary`
  - `task_progress`
  - `task_blocker`
  - `task_next_action`
  - `system_task`
  - `meta_task`
- `JudgeDecision`
  - `action`: `drop | long_term | task | mixed | rewrite`
  - `memory_kind`
  - `canonical_text`
  - `confidence`
  - `reason`
  - `noise_kind`
  - `task_kind_override`
  - `store_task_memory`: boolean

### `rules.py`

Hard-rule fast paths:

- exact empty/no-reply/reply markers
- exact cron prefixes
- exact known transport metadata banners
- exact current-time scaffold patterns
- oversized JSON-ish metadata blocks
- duplicate fingerprint checks

This layer should be deterministic and cheap. If it returns `drop`, no LLM call is made.

### `judge.py`

Structured LLM judge for ambiguous cases.

Inputs:

- user message
- assistant output
- metadata:
  - source agent
  - project id
  - route origin (`memory_route`, `task_summaries`, direct `/memories`)
  - auto-capture vs explicit write
  - candidate task id/title when present

Outputs:

- a strict JSON matching `JudgeDecision`

Use two prompts:

1. `online_memory_judge`
   For ingestion. Cheap, conservative, short canonical outputs.
2. `offline_compaction_judge`
   For consolidation. Can compare multiple entries and suggest keep/rewrite/merge/drop.

### `canonicalize.py`

Non-LLM canonicalization helpers:

- whitespace normalization
- category-specific canonical normalization for obvious preference aliases
- stable canonical ids / merge keys

Also host LLM-assisted canonicalization wrappers.

### `task_policy.py`

Centralize task-specific storage rules:

- derive `task_kind`
- decide whether a task row should exist
- decide whether task memory should be written
- prune memory writes for `system`, `meta`, `snapshot`, `cron`

This must be called before `/task-summaries` writes any memory rows.

### `consolidate.py`

Replace current narrow `/consolidate` implementation with a higher-level orchestrator:

- collect candidate long-term memory rows
- collect candidate task memory rows
- optionally normalize task rows
- optionally rebuild cache view
- batch items for compaction judge
- apply drop/rewrite/merge decisions

## API and Flow Changes

### 1. `POST /memory-route`

Current:

- heuristic route only

New:

1. strip recall wrappers and transport scaffolds
2. run hard-rule gate
3. run online memory judge when needed
4. only then emit `route`

Important changes:

- adapter-provided `task_like` becomes a weak hint, not an override
- response should include:
  - `judge`
  - `confidence`
  - `canonical_entries`

### 2. `POST /memories`

Current:

- direct writes can bypass richer routing semantics

New:

- direct writes still allowed, but go through the same governance entrypoint
- explicit long-term store may bypass route selection but not noise rejection
- `infer=True` should no longer be invisible to maintenance:
  - either cache inferred writes
  - or rebuild governance view from backend before consolidation

### 3. `POST /task-summaries`

Current:

- derive summary
- upsert task
- blindly write each summary field as task memory

New:

1. resolve/upsert task
2. classify task kind via `task_policy`
3. run judge on summary payload
4. if task kind is `system/meta/snapshot`, skip task memory writes
5. for `work` tasks, store only compact canonical fields approved by the judge

This is the most important noise-amplifier fix.

### 4. `POST /consolidate`

Current:

- preference-only canonicalization
- tiny task noise removal
- archive closed tasks

New:

- multi-phase governance job:
  1. optional task normalize
  2. optional cache rebuild or inferred-memory scan
  3. hard-rule garbage sweep
  4. semantic duplicate compaction
  5. category/rule canonicalization
  6. task snapshot pruning

Return richer metrics:

- `deleted_time_scaffold_count`
- `deleted_metadata_noise_count`
- `deleted_snapshot_task_memory_count`
- `merged_long_term_count`
- `rewritten_long_term_count`
- `normalized_tasks_count`

## Adapter Contract Redesign

### Common Contract

Adapters send:

- raw last user message
- raw last assistant output
- source agent
- project id
- capture trigger type
- session id / channel
- weak hints:
  - `explicit_long_term`
  - `candidate_task_like`

Adapters should no longer:

- force durable storage semantics
- force `task_like` as authoritative
- synthesize long-term categories locally beyond explicit user tools

### OpenCode

Problems:

- unconditional `--task-like`
- idle-triggered capture
- assistant streaming text appended naively

Changes:

- remove unconditional `--task-like`
- only pass `candidate_task_like`
- capture on stable completion, not generic idle
- dedupe by message/response id, not just full fingerprint
- wrap recall context in a backend-recognized marker format

### Claude Code

Problems:

- stop-hook capture on every turn
- no fingerprint dedupe
- session-start task recall too eager

Changes:

- add local fingerprint dedupe
- add minimal skip patterns
- move task recall behind backend-scored relevance
- do not auto-inject active tasks when relevance is low

### OpenClaw

Problems:

- wide `looksTaskLike`
- capture on every successful `agent_end`

Changes:

- keep `agent_end` capture but narrow local candidate gating
- rely on backend judge for final route
- keep recall wrapper format because backend can strip it cleanly

### Codex MCP

Problems:

- explicit tools can still store arbitrary text

Changes:

- direct `memory_store` should use backend governance when category is absent or broad
- document `memory_capture` as preferred path

## LLM Judge Design

### Online Judge Prompt Requirements

- classify whether content is:
  - durable cross-session context
  - real task progress
  - transient prompting or scaffold
  - transport/system metadata
- produce canonical short text
- default to `drop` on ambiguity

### Offline Compaction Judge Requirements

- compare similar entries in a batch
- choose:
  - keep canonical entry
  - rewrite to canonical text
  - merge into another entry
  - drop as transient/noise

### Model Strategy

- online: smaller, cheaper model for low latency
- offline: stronger model for batch compaction

### Safety

- LLM verdicts are schema-constrained
- rules still win for obvious garbage
- low confidence -> `drop` or `keep without merge`, never aggressive rewrite

## Data Migration Strategy

### One-Time Historical Cleanup

After code rollout:

1. run upgraded `tasks/normalize`
2. rebuild governance view/cache
3. run `/consolidate --dry-run`
4. inspect counts and sample diffs
5. run live `/consolidate`

### Historical Cleanup Rules

- delete time scaffolds
- delete raw conversation metadata
- delete cron and heartbeat task memory
- merge duplicated project rules/preferences
- keep only one canonical rule per semantic cluster

## Evaluation Strategy

Create a persistent eval set under a new path, for example:

```text
tests/evals/memory_governance/
├── online_judge_cases.jsonl
├── offline_compaction_cases.jsonl
└── expected_decisions.json
```

Case families:

- time prompts
- cron/watchdog instructions
- raw Feishu/Discord metadata
- transient system prompts
- real durable preferences
- real project rules
- valid task progress updates
- valid blockers/next actions
- semantic duplicates with different wording

Success criteria:

- obvious junk dropped with >95% precision
- valid durable memories retained with high recall
- system/meta tasks produce zero task memory

## Testing Plan

### Unit Tests

- governance rule classification
- long-term extraction after gating
- task kind gating before memory writes
- canonicalization functions

### Integration Tests

- `memory-route` on noisy vs valid payloads
- `task-summaries` for work vs system/meta tasks
- `consolidate` deletes historical noise families
- inferred-memory path remains governable

### Adapter Tests

- OpenCode no longer always sets task-like
- OpenCode capture dedupe on repeated stream/update events
- Claude capture dedupe
- OpenClaw candidate gating

### Dry-Run Assertions

- scheduled job can report planned deletes/merges without mutating
- live run counts match dry-run within tolerances

## Rollout Plan

### Phase 1: Backend Guardrails

- add governance package
- route `/memory-route` and `/task-summaries` through it
- add tests

### Phase 2: Adapter Thinning

- narrow adapter heuristics
- add dedupe/fingerprint protections
- align recall wrapper format

### Phase 3: Consolidation Upgrade

- expand `/consolidate`
- optionally chain `/tasks/normalize`
- add metrics

### Phase 4: Historical Migration

- run dry-run
- inspect samples
- run live cleanup

## Risks and Mitigations

- Risk: LLM over-drops borderline useful memory.
  Mitigation: conservative prompts, confidence thresholds, eval set.
- Risk: adapter and backend behavior diverge.
  Mitigation: backend is source of truth; adapters send weak hints only.
- Risk: migration deletes too much.
  Mitigation: dry-run, metrics, sampled diffs, staged rollout by user/project scope.
- Risk: online latency increases.
  Mitigation: rules fast-path plus small structured model for online judge.

## Recommended First Implementation Slice

Implement these first before anything else:

1. central governance package skeleton
2. `task_summaries` task-kind gate
3. online judge integration in `memory-route`
4. tests for time prompt / cron / metadata rejection

Those four changes remove the biggest noise amplifier while keeping the rest of the system intact.
