# Project Milestones: automem

## v1.0 milestone (Shipped: 2026-04-16)

**Delivered:** A shipped shared-memory control plane with fail-closed auth, backend-owned governance, shared project scope, explainable hybrid retrieval, temporal fact lifecycle support, and a production-shaped API/worker/MCP runtime split.

**Phases completed:** 01-09 (15 plans, 44 tasks)

**Key accomplishments:**

- Authentication now fails closed, and non-admin API keys must bind to real users before they can touch shared memory or task state.
- Memory and task admission now flow through backend-owned governance, while adapters keep only cheap local suppression and duplicate control.
- Maintenance flows now refresh cache before scanning, rewrite canonicals safely, and run scheduled consolidation with basic overlap and retry protection.
- Project-scoped identity enforcement now spans memory reads, writes, deletes, and CLI key creation without regressing existing adapter compatibility.
- Hybrid retrieval now returns explicit semantic, lexical, and metadata match reasons, while task alias metadata can pull the right task memory back into search results.
- Long-term memory now behaves like evolving facts, and the governance runtime is now split cleanly between hot-path API admission and background worker execution.
- Foundational verification and milestone-wide Nyquist validation were backfilled so v1.0 now has a complete close-out evidence chain.

**Stats:**

- 97 files changed
- 12,826 insertions and 467 deletions across the milestone git range
- 9 phases, 15 plans, 44 tasks
- 19 days from initial repo publish to v1.0 archive

**Git range:** `bd66d8f` → `1f89bc9`

**What's next:** Run `$gsd-new-milestone` to define the next milestone's requirements and roadmap.

---
