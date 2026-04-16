# Phase 11: Deep-User Workflow And Scope Regression - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md and the scope model doc — this log preserves the key tradeoffs and conclusions from the interactive discuss session.

**Date:** 2026-04-17
**Phase:** 11-deep-user-workflow-and-scope-regression
**Areas discussed:** Retrieval quality, Fact lifecycle, Task handoff and cleanup, Scope model, Mixed-scope retrieval, Migration

---

## Retrieval quality

### Priority of failures

| Option | Description | Selected |
|--------|-------------|----------|
| Missed recall first | The worst failure is that a memory should have been found but was not found | ✓ |
| Ranking first | Results exist, but wrong ranking is the main concern | |
| Explanation first | Explainability matters most even before recall and ranking | |
| Scope leakage first | Retrieval quality is mainly about project boundary safety | |

**User's choice:** Missed recall first, ranking second, explanation third, scope leakage fourth
**Notes:** Retrieval quality should first protect against “应该找到但没找到”, then wrong ranking, then misleading explanation. Scope leakage is still important but belongs more naturally to the dedicated scope-safety track.

### Golden retrieval stories

| Option | Description | Selected |
|--------|-------------|----------|
| Intent-style recall of long-term memory | A query phrased as a user intent should still retrieve the right long-term memory | ✓ |
| Task-next-step recall | “What is next?” style queries should reliably surface task memory | |
| Current fact outranks history | After a fact changes, default retrieval must prioritize the active version | ✓ |
| User-supplied custom example | A different story becomes the primary retrieval anchor | |

**User's choice:** Intent-style recall of long-term memory; current fact outranks history
**Notes:** The canonical example is a stored preference such as “偏好使用中文沟通” being retrievable from an intent-style query like “我应该用什么语言回复你”. Current facts must rank ahead of superseded history by default.

### Current versus history behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Strong current-first | Default retrieval should almost only show the active fact | |
| Current-first with history trace | Active fact must lead, but history should leave a visible trace | ✓ |
| History stays prominent | History should remain highly visible even in ordinary queries | |

**User's choice:** Current-first with history trace
**Notes:** Active facts must be clearly first, but retrieval should still leave a small trace that a fact has history or review state.

### Intent-query acceptance threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Any hit is enough | Relevant memory appearing anywhere in the result set is acceptable | |
| Top-3 stability | The right result must reliably appear in the top three | ✓ |
| Top-1 only | Core identity/preference memories must always rank first | |

**User's choice:** Top-3 stability
**Notes:** The system should do better than “it showed up somewhere”, but Phase 11 does not require an unrealistic “always rank #1” guarantee for every intent-style query.

### Dynamic ranking classes

| Option | Description | Selected |
|--------|-------------|----------|
| Identity / preference queries | Queries about who the user is or how to respond | ✓ |
| Task-status queries | Queries about next step, progress, blocker, handoff | ✓ |
| Project-context queries | Queries about what a project is and its background | ✓ |
| Fact-history queries | Queries that explicitly ask about previous values or changes | ✓ |

**User's choice:** All four
**Notes:** Phase 11 should explicitly cover all four classes and treat ranking as query-type-aware, not one global ordering rule.

### Explanation style for core queries

| Option | Description | Selected |
|--------|-------------|----------|
| Field-only explainability | Debug fields are enough; no natural-language explanation needed | |
| Short natural-language explanation with evidence | Explain query type and why the winning result ranked first | ✓ |
| Full audit-style explanation | Include detailed ranking breakdown and all losing candidates | |

**User's choice:** Short natural-language explanation with evidence
**Notes:** The explanation should be concise and human-readable, but it must still point to real reasons rather than a polished story.

### Explanation failure priorities

| Option | Description | Selected |
|--------|-------------|----------|
| Fabricated reasons | Explanation sounds plausible but is not the true ranking reason | ✓ |
| Mismatch with ranking | Explanation says one thing, ranking behavior does another | ✓ |
| Too little evidence | Explanation gives a conclusion but not enough basis | ✓ |
| Too technical | Explanation exposes too much system jargon | |

**User's choice:** Fabricated reasons first, mismatch second, insufficient evidence third
**Notes:** Core-query explanations must be grounded in the actual retrieval behavior. The main risk is false rationalization.

---

## Fact lifecycle

### Priority of failures

| Option | Description | Selected |
|--------|-------------|----------|
| New fact fails to replace old fact | Updated facts do not correctly become the default active version | ✓ |
| Wrong auto-supersede | A fact that should have gone to review is auto-replaced | ✓ |
| History state corruption | Active, superseded, and review states drift out of sync | |
| History query UX | Asking about old values behaves badly | |

**User's choice:** New fact must correctly replace old fact; wrong auto-supersede is the second concern
**Notes:** Fact lifecycle should first ensure “替得对”, then ensure “别替错”.

### Auto-supersede boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Preference and identity only | Auto-supersede is narrow and conservative | |
| Preference only | Even identity facts should remain more review-heavy | |
| Preference, identity, and part of project context | Auto-supersede may include some project context when confidence is high | ✓ |

**User's choice:** Preference, identity, and part of project context
**Notes:** The user explicitly wanted a broader but still guarded model where some project-context facts can auto-supersede when the system has enough confidence.

### Supersede decision method

| Option | Description | Selected |
|--------|-------------|----------|
| White-list fields only | Only preapproved fact types may auto-supersede | |
| White-list fields plus semantic judgment | Allowed fact types may auto-supersede when the new text is clearly the next version of the same fact | ✓ |
| Mostly semantic judgment | Let semantic similarity drive most decisions | |

**User's choice:** White-list fields plus semantic judgment
**Notes:** This is the main safety rail: auto-supersede must stay inside an approved fact-type boundary and then still pass a same-fact/new-version test.

### White-list candidates

| Option | Description | Selected |
|--------|-------------|----------|
| Language preference | Communication language preference | ✓ |
| Output style preference | Summary style, directness, verbosity | ✓ |
| Identity facts | Name, role, title, similar user-profile facts | ✓ |
| Some project context | Fixed or near-fixed project facts plus selected current-work context | ✓ |

**User's choice:** All four
**Notes:** The broadest agreed white-list still requires review fallback when confidence drops.

### Project-context breadth and fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Only fixed single-value project facts | Company, main project, stable identifiers only | |
| Fixed facts plus some current-work context | Current work focus and workflow can participate when evidence is strong | ✓ |
| Broad semantic project context | Most current project facts may auto-supersede | |

**User's choice:** Fixed facts plus some current-work context
**Notes:** This widens auto-supersede, but every unstable or risky signal should force a fallback to `conflict_review`.

### Review fallback rule

| Option | Description | Selected |
|--------|-------------|----------|
| Review on large wording drift | Only strong textual divergence forces review | |
| Review on high-value facts only | Keep review mostly for company/project-level fields | |
| Review when any strong uncertainty appears | Any major uncertainty should stop auto-supersede | ✓ |

**User's choice:** Review when any strong uncertainty appears
**Notes:** Even with a broad white-list, uncertainty should fail safe into review.

### History visibility

| Option | Description | Selected |
|--------|-------------|----------|
| Current only by default | History appears only when explicitly requested | |
| Current first with same-screen trace | Current fact leads, but history leaves a visible trace | ✓ |
| History remains prominent | History is intentionally obvious in normal retrieval | |

**User's choice:** Current first with same-screen trace
**Notes:** This matches the retrieval conclusion: active fact first, but with enough trace to understand that older or review states exist.

---

## Task handoff and cleanup

### Priority of failures

| Option | Description | Selected |
|--------|-------------|----------|
| Handoff exists but next agent cannot continue | Summary exists, but does not actually enable the next agent to pick up the work | ✓ |
| Cleanup is insufficient | Noise and stale tasks remain and interfere with later work | ✓ |
| Materialization instability | Real work sometimes fails to materialize or noise sometimes materializes | ✓ |
| Cleanup is too aggressive | Valuable task memory is deleted too early | |

**User's choice:** Handoff continuity first, insufficient cleanup second, materialization instability third
**Notes:** The user emphasized that the system should make it easier for the next agent to pick the right task, not just show many tasks.

### What “handoff works” means

| Option | Description | Selected |
|--------|-------------|----------|
| Clear next action | The next agent can immediately see what to do next | ✓ |
| Clear current state | The next agent can quickly understand progress so far | ✓ |
| Clear rationale | The next agent can understand why the work matters | ✓ |

**User's choice:** All three, with priority `next_action > progress/current state > why`
**Notes:** A handoff is good when it is actionable first, contextual second, explanatory third.

### Acceptance threshold for handoff continuity

| Option | Description | Selected |
|--------|-------------|----------|
| Searchable handoff is enough | If the handoff memory can be found, the story passes | |
| Searchable and actionable | The handoff must contain enough next-action signal to continue | |
| Multi-hop continuity | A second agent must be able to continue, update state, and leave a handoff that a third agent can also continue from | ✓ |

**User's choice:** Multi-hop continuity
**Notes:** The standard is not “retrieved once”, but “can sustain sequential continuation across agents”.

### Fields that must survive every hop

| Option | Description | Selected |
|--------|-------------|----------|
| Next action | What to do next | ✓ |
| Progress/current state | What is already done and where the task stands | ✓ |
| Blocker/risk | What is blocking progress | |
| Task identity | Proof that the handoff still belongs to the same task | ✓ |

**User's choice:** Next action, progress/current state, and task identity are mandatory; blockers matter when present but are not mandatory every time
**Notes:** Good handoff preserves “what this is, where it is, and what happens next”.

### Cleanup philosophy

| Option | Description | Selected |
|--------|-------------|----------|
| Archive quickly | Remove from active view first, keep data around | |
| Delete quickly | Erase obvious noise as soon as possible | |
| Layered cleanup | Aggressive on obvious system noise, gentler on once-useful but now stale work | ✓ |

**User's choice:** Layered cleanup
**Notes:** Cleanup should protect later agents from picking the wrong thing, not simply minimize data volume.

### Most aggressive cleanup target

| Option | Description | Selected |
|--------|-------------|----------|
| Clear system noise | cron/watchdog/system reminders/media/transport metadata | ✓ |
| Empty or fake handoffs | Summaries with no actionable continuity | |
| Old superseded task state | Historical task memory that now confuses retrieval | |

**User's choice:** Clear system noise
**Notes:** System noise should be handled most aggressively because it is the least likely to become useful work later.

### Materialization bias

| Option | Description | Selected |
|--------|-------------|----------|
| Prefer recall of true tasks | Materialize more aggressively so real work is not missed | |
| Prefer precision and cleanliness | Materialize more conservatively to avoid polluting the task space | ✓ |

**User's choice:** Prefer precision and cleanliness
**Notes:** The system should be conservative: better to miss some marginal task materialization than to let noise become handoff-visible work.

### One-line goal

**User's conclusion:** The next agent should find it easier to pick the right task, not easier to see more tasks.

---

## Scope model and mixed-scope retrieval

### Primary scope model

| Option | Description | Selected |
|--------|-------------|----------|
| Two primary scopes only | `user_global` and `project`; `task` is organizational only | ✓ |
| Three primary scopes | Add `task` as a first-class access scope | |
| Keep implicit `project_id` model | Retain the current primary shape | |

**User's choice:** Two primary scopes only
**Notes:** `task` is an organization dimension, not a primary isolation layer.

### Project retrieval inheritance

| Option | Description | Selected |
|--------|-------------|----------|
| Project inherits global by default | Project retrieval includes project state plus user-global context | ✓ |
| Project retrieval requires explicit global inclusion | No inheritance unless the caller asks for it | |
| Strict isolation always | Project retrieval only ever sees project-scoped records | |

**User's choice:** Project inherits global by default
**Notes:** This reduces “should have found it but didn’t” regressions when stable preferences and project context need to coexist.

### Ambiguous writes

| Option | Description | Selected |
|--------|-------------|----------|
| Do not guess outside single-project context | Ambiguous writes require explicit scope unless a single project clearly owns the request | ✓ |
| Default to user-global | Ambiguous writes should fall global by default | |
| Default to project | Ambiguous writes should fall into the active project by default | |

**User's choice:** Do not guess outside single-project context
**Notes:** Runtime behavior remains conservative even though migration later may classify many legacy records automatically.

### `agent_id` role

| Option | Description | Selected |
|--------|-------------|----------|
| Attribution and audit | Keep it for source identity, but not as the main scope boundary | ✓ |
| Strong isolation dimension | Keep it as a significant access boundary | |
| Logging only | Largely minimize its semantic role | |

**User's choice:** Attribution and audit
**Notes:** `agent_id` should not carry the burden of primary scope semantics.

### Project overview split

| Option | Description | Selected |
|--------|-------------|----------|
| Global overview only | Put project summary mostly in user-global space | |
| Project-only overview | Keep project overview strictly local | |
| Split overview and status | Put overview/index/stable constraints in global scope and detailed state in project scope | ✓ |

**User's choice:** Split overview and status
**Notes:** This was a key conclusion: global should carry maps and stable constraints; project should carry the moving state.

### Global project-index depth

| Option | Description | Selected |
|--------|-------------|----------|
| Identification only | Just what the project is | |
| Identification plus stable constraints | What the project is plus stable long-term boundaries and constraints | ✓ |
| Include current focus too | Also include current work focus in the global project index | |

**User's choice:** Identification plus stable constraints
**Notes:** Current detailed status should not be folded into the global layer by default.

### High-ambiguity “current state” records

| Option | Description | Selected |
|--------|-------------|----------|
| Default to project | Treat current-focus/current-workflow statements as project-local | |
| Default to global | Treat them as user-wide current state | |
| Require more evidence or explicit scope | Do not decide automatically | ✓ |

**User's choice:** Require more evidence or explicit scope
**Notes:** Current-focus/current-workflow statements are explicitly treated as high-ambiguity records.

### Mixed-scope retrieval ordering

| Option | Description | Selected |
|--------|-------------|----------|
| Always prefer project | In project context, rank project-scoped results first | |
| Query-type-aware bias | Let the main query intent decide whether global or project should dominate | ✓ |
| Separate channels | Return both scopes in visibly separate sections | |

**User's choice:** Query-type-aware bias
**Notes:** Identity/preference/project-index queries should lean global; task-status/handoff/project-state queries should lean project.

### Mixed-query behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Project-first | Project answers always lead when the query is mixed | |
| Global-first | Global stable context always leads when the query is mixed | |
| Main answer plus support | Main answer follows dominant intent; the other scope remains as supporting context | ✓ |

**User's choice:** Main answer plus support
**Notes:** The non-dominant scope should remain visible enough to matter, not disappear completely.

### How to explain mixed-scope answers

| Option | Description | Selected |
|--------|-------------|----------|
| Name the raw scope types | Explain with internal terms like `user_global` and `project_scoped` | |
| Explain by role | Describe “current project state” versus “cross-project preferences and stable constraints” | ✓ |
| Avoid source-role explanation | Explain only the answer, not where it came from | |

**User's choice:** Explain by role
**Notes:** User-facing explanations should describe the role of the source, not expose internal scope labels directly.

### Strict project-only mode

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit parameter | Strict mode is triggered only when the caller asks for it directly | ✓ |
| Automatic on sensitive query classes | Some queries silently switch into strict mode | |
| Maintenance-only | Strict mode exists only for operators and tests | |

**User's choice:** Explicit parameter
**Notes:** Default behavior should optimize for useful inheritance; strictness should be a deliberate caller choice.

---

## Migration direction

### Target cutover shape

| Option | Description | Selected |
|--------|-------------|----------|
| API only | Change the external API first and leave old internal semantics for now | |
| Full clean cut | Move API, internals, and stored records to explicit `scope` together | ✓ |

**User's choice:** Full clean cut
**Notes:** The user wanted the old `project_id`-as-meaning model removed rather than preserved under the new surface.

### Migration style

| Option | Description | Selected |
|--------|-------------|----------|
| Conservative migration | Only migrate records automatically when the destination is obvious | |
| Mostly automatic migration | Migrate the large majority of records automatically and reserve a small review bucket for truly ambiguous cases | ✓ |
| Coarse migration first | Move everything quickly and repair semantics later | |

**User's choice:** Mostly automatic migration
**Notes:** Runtime behavior should stay conservative, but migration should do more work up front so the system does not carry ambiguity forever.

### Strong `project` evidence

**Selected signals:**

- explicit `project_id`
- `task_id` or `run_id`
- `task`-domain memory like `handoff`, `progress`, `blocker`, `next_action`
- `project_context` content that clearly behaves like current state
- records that cluster strongly into the same project

### Strong `user_global` evidence

**Selected signals:**

- `user_profile` or `preference`
- stable facts without task/project binding
- project-overview content
- obvious cross-project reuse value
- map/index-style content rather than current status

### Conflict and fallback

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed side wins | Always choose either project or global when signals conflict | |
| Evidence-tier resolution | Hard structural evidence outranks semantic evidence; semantic evidence outranks weak hints | ✓ |

**User's choice:** Evidence-tier resolution
**Notes:** Strong structural evidence should win over semantic hints; weak hints should only help break ties.

| Option | Description | Selected |
|--------|-------------|----------|
| Default to global on weak evidence | Preserve visibility rather than restrict | |
| Default to project on weak evidence | Avoid cross-project pollution first | |
| `migration_review` bucket | Truly weak evidence should route to review instead of forcing a guess | ✓ |

**User's choice:** `migration_review` bucket
**Notes:** The system should mostly auto-migrate, but it should not invent certainty when there is not enough evidence.

---

## the agent's Discretion

- Exact scenario naming
- Test module boundaries and helper extraction
- Whether a given regression reads better as a matrix or as separate named tests
- Exact wording of natural-language explanations, as long as they stay faithful to the true ranking reasons

## Deferred Ideas

- Full browser E2E expansion
- Broad adapter/runtime matrix expansion
- Real-dependency contract lanes for mem0 or Qdrant
