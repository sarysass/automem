# Backend main.py Decomposition — Phases 11–15 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `backend/main.py` from 2692 → ~400 lines by extracting routing, task storage, business services, and HTTP routers into focused modules, while keeping all 186 tests green and the production VPS healthy.

**Architecture:** Mechanical, non-invasive extraction. Each phase produces one new module + edits in `backend/main.py` that re-export the moved symbols (`# noqa: F401`) so external callers, tests, and `scripts/governance_worker.py` keep working. Phase 11 first replaces every `sqlite3.connect(TASK_DB_PATH)` with `sqlite3.connect(_resolve_task_db_path())`, removing the module-isolation bug that killed the previous routing extraction attempt.

**Tech Stack:** FastAPI, SQLite (WAL mode), mem0ai, pytest, ruff. Tests use `importlib.spec_from_file_location` reload pattern (see `tests/conftest.py`) — extracted modules MUST NOT capture `TASK_DB_PATH` at module load time.

---

## Background — Why this plan exists

Previous extraction work (Phases 1–10) removed 11 modules and cut main.py 45%. Phase 10 (routing) was attempted and reverted because `from backend.main import fetch_tasks` inside `routing.py.resolve_task()` resolves to the canonical `backend.main` module, not the test fixture's `automem_backend_<tmp>` instance. That instance has stale `TASK_DB_PATH`, so all task lookups hit the wrong DB.

**Root cause:** Functions that called `sqlite3.connect(TASK_DB_PATH)` captured the module-level `TASK_DB_PATH` constant at the moment the canonical `backend.main` was first imported. Once that constant is captured, monkeypatch in conftest can't change it back.

**Fix:** `backend/storage.py:_resolve_task_db_path()` reads `os.environ["TASK_DB_PATH"]` at call time. Routing all SQLite access through that resolver makes every function env-transparent. Phase 11 below converts the 14 remaining call sites.

---

## File Structure

After all phases:

```
backend/
  main.py                ~400 lines: lifespan + get_memory_backend + app + include_router
  routing.py             NEW ~250 lines: route_memory + resolve_task + task_candidate_score
  task_storage.py        NEW ~350 lines: fetch_tasks + fetch_tasks_page + normalize_tasks +
                                          hydrate_task_row + cursor encode/decode +
                                          fetch_task_search_context + upsert_task +
                                          fetch_task_ids_with_memory
  services.py            NEW ~600 lines: store_memory_with_governance +
                                          run_consolidation_operation + rebuild_memory_cache +
                                          archive_active_long_term_facts +
                                          dispatch_governance_job
  search_pipeline.py     NEW ~400 lines: hybrid_search + rerank_results + lexical_score +
                                          merge_search_candidate + finalize_search_result +
                                          matched_filter_fields
  routers/
    __init__.py
    health.py            NEW ~30 lines: GET /, GET /favicon.ico, GET /v1/ui, GET /v1/healthz,
                                          GET /v1/runtime-topology, GET /v1/metrics
    memories.py          NEW ~120 lines: POST /v1/memories, GET /v1/memories,
                                          GET /v1/memories/{id}, DELETE /v1/memories/{id},
                                          POST /v1/search, POST /v1/memory-route,
                                          POST /v1/cache/rebuild
    tasks.py             NEW ~150 lines: POST /v1/task-resolution, POST /v1/task-summaries,
                                          GET /v1/tasks, GET /v1/tasks/{id},
                                          POST /v1/tasks/{id}/close,
                                          POST /v1/tasks/{id}/archive,
                                          POST /v1/tasks/normalize
    governance.py        NEW ~80 lines: POST /v1/consolidate, POST /v1/governance/jobs,
                                          GET /v1/governance/jobs,
                                          GET /v1/governance/jobs/{id},
                                          POST /v1/governance/jobs/run-next
    admin.py             NEW ~50 lines: POST /v1/agent-keys, GET /v1/agent-keys,
                                          GET /v1/audit-log
```

---

## Phase 11 — Replace TASK_DB_PATH call sites

**Goal:** Make every `sqlite3.connect(...)` in `backend/main.py` env-transparent, unblocking module extraction. **No size reduction.** This is purely a setup commit.

**Files:**
- Modify: `backend/main.py` (14 sites — see line numbers in step 1)

**Affected line numbers (current):** 773, 873, 1219, 1296, 1418, 1465, 1498, 1518, 1644, 2196, 2215, 2246, 2360, 2417

### Task 11.1: Replace all 14 sites

- [ ] **Step 1: Verify _resolve_task_db_path is already imported in main.py**

Run: `grep -n "_resolve_task_db_path" backend/main.py | head -5`
Expected: at least one match in the imports block at top of file. If missing, add to existing `from backend.storage import (...)` block.

- [ ] **Step 2: Bulk-replace via sed**

```bash
sed -i.bak 's/sqlite3\.connect(TASK_DB_PATH)/sqlite3.connect(_resolve_task_db_path())/g' backend/main.py
diff backend/main.py.bak backend/main.py | head -50
rm backend/main.py.bak
```

Expected: 14 lines changed, no other diffs.

- [ ] **Step 3: Verify no TASK_DB_PATH-as-arg call sites remain**

Run: `grep -n "sqlite3.connect(TASK_DB_PATH)" backend/main.py`
Expected: zero matches.

Run: `grep -c "sqlite3.connect(_resolve_task_db_path())" backend/main.py`
Expected: 14.

- [ ] **Step 4: Run full test suite + ruff**

Run: `uv run pytest -x -q && uv run ruff check backend tests scripts`
Expected: 186 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): route all SQLite connects through _resolve_task_db_path()

Replaces 14 sqlite3.connect(TASK_DB_PATH) call sites in main.py with
sqlite3.connect(_resolve_task_db_path()), reading TASK_DB_PATH from
os.environ at call time. This makes every SQLite-touching function
transparent to env changes across module boundaries, unblocking
routing/task_storage/services extraction (Phases 12-14).

No behavior change. 186 tests still green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 12 — Extract backend/routing.py

**Goal:** Move hot-path routing logic out of main.py.

**Files:**
- Create: `backend/routing.py` (~250 lines)
- Modify: `backend/main.py` (delete ~280 lines, add 4-line re-export block)

**Functions moved:** `route_memory` (main.py:486-620), `task_candidate_score` (1687-1727), `resolve_task` (1729-1802)

### Task 12.1: Create routing.py with the three functions

- [ ] **Step 1: Read the source ranges to get exact code**

Run: `sed -n '486,620p;1687,1802p' backend/main.py > /tmp/routing_source.py && wc -l /tmp/routing_source.py`
Expected: ~250 lines.

- [ ] **Step 2: Identify cross-module dependencies**

Inside `route_memory` and `resolve_task`, list every name they reference that is either:
- defined in `backend/main.py` (e.g. `MEMORY_BACKEND`, `store_memory_with_governance`, `fetch_tasks`)
- imported from another `backend/*` module

For dependencies still in main.py (`MEMORY_BACKEND`, `store_memory_with_governance`, `fetch_tasks`, `fetch_task_ids_with_memory`, `upsert_task`, `normalize_tasks`):
- Use a lazy `from backend import main as _main` inside the function body, NOT at module top.
- Access them as `_main.fetch_tasks(...)`, `_main.MEMORY_BACKEND`.

This is the same pattern `backend/search.py:_category_sets()` uses successfully.

- [ ] **Step 3: Write backend/routing.py**

```python
"""Hot-path routing for memory writes + task resolution.

route_memory  — POST /v1/memory-route handler body. Decides whether a
                turn lands as long-term memory, task summary, both, or
                neither. Calls store_memory_with_governance + resolve_task.
resolve_task  — POST /v1/task-resolution handler body. Picks the best
                existing task or creates a new one for an incoming
                message.
task_candidate_score — Pure scoring helper used by resolve_task.

Dependencies on backend.main (MEMORY_BACKEND, store_memory_with_governance,
fetch_tasks, fetch_task_ids_with_memory, upsert_task, normalize_tasks)
are resolved lazily via `from backend import main as _main` inside each
function body, to stay compatible with the test fixture's
importlib.spec_from_file_location reload pattern (tests/conftest.py).
"""

from __future__ import annotations

# ... full bodies of route_memory, task_candidate_score, resolve_task ...
# ... with cross-module deps changed to _main.X ...

__all__ = ["resolve_task", "route_memory", "task_candidate_score"]
```

(The full code is ~250 lines — extract verbatim from main.py and only edit cross-module references.)

- [ ] **Step 4: Delete the three function bodies from main.py**

Open `backend/main.py`, delete:
- lines for `def route_memory(...)` through end of body (~135 lines)
- lines for `def task_candidate_score(...)` through end of body (~40 lines)
- lines for `def resolve_task(...)` through end of body (~75 lines)

Add to imports block (alphabetical):

```python
from backend.routing import (  # noqa: F401  (re-exported for tests + worker)
    resolve_task,
    route_memory,
    task_candidate_score,
)
```

- [ ] **Step 5: Update FastAPI handler call sites**

Two `@app.post` handlers reference these by bare name:

```python
@app.post("/v1/memory-route")
def memory_route(payload: MemoryRouteRequest, ...):
    ...
    return route_memory(payload)  # already works after re-export

@app.post("/v1/task-resolution")
def task_resolution(payload: TaskResolutionRequest, ...):
    ...
    return resolve_task(payload)  # already works after re-export
```

The re-export above keeps these unchanged. Verify with grep:

Run: `grep -n "route_memory(payload)\|resolve_task(payload)" backend/main.py`
Expected: both still present.

- [ ] **Step 6: Run full pytest**

Run: `uv run pytest -x -q`
Expected: 186 passed. If any test fails with "wrong DB" or "task not found", a `_resolve_task_db_path()` site was missed in Phase 11 — fix and re-run.

- [ ] **Step 7: Run ruff**

Run: `uv run ruff check backend tests scripts`
Expected: clean.

- [ ] **Step 8: Verify main.py size**

Run: `wc -l backend/main.py`
Expected: ~2440 lines (down from 2692, -250).

- [ ] **Step 9: Commit**

```bash
git add backend/routing.py backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): extract route_memory + resolve_task to backend/routing.py

Pulls the hot-path routing decisions (route_memory, resolve_task,
task_candidate_score) out of main.py into a focused module. Cross-module
references back to main.py (MEMORY_BACKEND, store_memory_with_governance,
fetch_tasks, etc.) use lazy `from backend import main as _main` to stay
compatible with the test conftest's importlib reload pattern.

main.py: 2692 -> ~2440 lines.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 13 — Extract backend/task_storage.py

**Goal:** Move all task-table CRUD/query helpers out of main.py.

**Files:**
- Create: `backend/task_storage.py` (~350 lines)
- Modify: `backend/main.py` (delete ~350 lines, add re-export)

**Functions moved:**
- `hydrate_task_row` (main.py:1358-1372)
- `encode_task_cursor` (1374-1377)
- `decode_task_cursor` (1379-1390)
- `fetch_tasks_page` (1392-1429)
- `fetch_tasks` (1431-1444)
- `fetch_task_ids_with_memory` (1446-1468)
- `normalize_tasks` (1470-1637)
- `upsert_task` (1639-1685)
- `fetch_task_search_context` (854-885)

### Task 13.1: Create task_storage.py

- [ ] **Step 1: Capture current source ranges**

Run:
```bash
sed -n '854,885p' backend/main.py > /tmp/ts1.py
sed -n '1358,1685p' backend/main.py > /tmp/ts2.py
wc -l /tmp/ts1.py /tmp/ts2.py
```
Expected: ts1 ~32 lines, ts2 ~330 lines.

- [ ] **Step 2: Write backend/task_storage.py**

Module docstring:

```python
"""Task table storage: row hydration, pagination cursors, page/list/normalize/upsert.

Keeps all SQLite + sqlite3.Row → dict translation in one place. Uses
_resolve_task_db_path() at call time so each invocation reads the
current TASK_DB_PATH (test fixtures monkeypatch.setenv it per-test).

Cross-module call backs to backend.main (MEMORY_BACKEND for
fetch_task_search_context's mem0 query, hash_token, utcnow_iso) are
resolved via direct imports from backend.storage where possible.
MEMORY_BACKEND specifically is fetched lazily via
`from backend import main as _main; _main.MEMORY_BACKEND`.
"""
```

Copy each function verbatim from main.py, swap `TASK_DB_PATH` references for `_resolve_task_db_path()` (already done in Phase 11), and rewrite cross-module deps:
- `hash_token`, `utcnow_iso`, `now_epoch` → already in `backend.storage`
- `MEMORY_BACKEND` → `_main.MEMORY_BACKEND` via lazy import inside function body
- `extract_task_lookup_subject`, `split_sentences` → from `backend.tasks`

End with:

```python
__all__ = [
    "decode_task_cursor",
    "encode_task_cursor",
    "fetch_task_ids_with_memory",
    "fetch_task_search_context",
    "fetch_tasks",
    "fetch_tasks_page",
    "hydrate_task_row",
    "normalize_tasks",
    "upsert_task",
]
```

- [ ] **Step 3: Delete the function bodies from main.py**

Delete the 9 function definitions listed above. Add to imports block:

```python
from backend.task_storage import (  # noqa: F401  (re-exported for tests)
    decode_task_cursor,
    encode_task_cursor,
    fetch_task_ids_with_memory,
    fetch_task_search_context,
    fetch_tasks,
    fetch_tasks_page,
    hydrate_task_row,
    normalize_tasks,
    upsert_task,
)
```

- [ ] **Step 4: Run pytest**

Run: `uv run pytest -x -q`
Expected: 186 passed.

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check backend tests scripts`
Expected: clean.

- [ ] **Step 6: Verify size**

Run: `wc -l backend/main.py backend/task_storage.py`
Expected: main.py ~2090, task_storage.py ~350.

- [ ] **Step 7: Commit**

```bash
git add backend/task_storage.py backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): extract task table storage to backend/task_storage.py

Moves hydrate_task_row, encode/decode_task_cursor, fetch_tasks(_page),
fetch_task_ids_with_memory, fetch_task_search_context, normalize_tasks,
upsert_task into a dedicated module. Re-exports from main.py keep test
fixtures and routing.py importing the same names.

main.py: ~2440 -> ~2090 lines.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 14 — Extract backend/services.py + backend/search_pipeline.py

**Goal:** Move business orchestration + search pipeline into focused modules.

### Task 14.1: Create backend/search_pipeline.py first (smaller, fewer deps)

**Functions moved:**
- `lexical_score` (main.py:844-852)
- `matched_filter_fields` (887-902)
- `merge_search_candidate` (904-931)
- `finalize_search_result` (933-959)
- `rerank_results` (961-1076)
- `hybrid_search` (1078-1356)

**Files:**
- Create: `backend/search_pipeline.py` (~400 lines)
- Modify: `backend/main.py` (delete ~510 lines, re-export)

- [ ] **Step 1: Capture source**

Run: `sed -n '844,1356p' backend/main.py | wc -l`
Expected: ~513 lines.

- [ ] **Step 2: Write backend/search_pipeline.py**

Docstring:

```python
"""Hybrid search pipeline: vector + lexical + rerank + filter-match.

hybrid_search  — Top-level entry: takes a SearchRequest, runs vector
                 search through MEMORY_BACKEND, hydrates with task
                 metadata, applies category preferences, reranks.
rerank_results — Reorders mem0 results using lexical_score + filter
                 matches + category preferences.
lexical_score  — Substring overlap heuristic.
merge_search_candidate / finalize_search_result / matched_filter_fields
               — Result-shape helpers.
"""
```

Use lazy `_main.MEMORY_BACKEND` for the vector backend reference inside `hybrid_search`. Other deps (`classify_query_intent`, `build_vector_query`, `choose_mixed_scope_answer_roles`) come from `backend.search`. Task lookups go through `backend.task_storage.fetch_task_search_context`.

- [ ] **Step 3: Delete from main.py + add re-export**

```python
from backend.search_pipeline import (  # noqa: F401
    finalize_search_result,
    hybrid_search,
    lexical_score,
    matched_filter_fields,
    merge_search_candidate,
    rerank_results,
)
```

- [ ] **Step 4: pytest + ruff**

Run: `uv run pytest -x -q && uv run ruff check backend tests scripts`
Expected: 186 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/search_pipeline.py backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): extract hybrid_search pipeline to backend/search_pipeline.py

Moves hybrid_search + rerank_results + lexical_score + merge/finalize
helpers into a dedicated module. backend/search.py keeps the pure
intent-classification helpers; the pipeline that combines vector + lexical
results lives separately.

main.py: ~2090 -> ~1580 lines.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 14.2: Create backend/services.py

**Functions moved:**
- `store_memory_with_governance` (main.py:312-484)
- `dispatch_governance_job` (622-692)
- `rebuild_memory_cache` (734-783)
- `archive_active_long_term_facts` (785-842)
- `run_consolidation_operation` (2318-2536)

**Files:**
- Create: `backend/services.py` (~600 lines)
- Modify: `backend/main.py` (delete ~600 lines, re-export)

- [ ] **Step 1: Write backend/services.py**

Docstring:

```python
"""Business service layer: memory write + cache rebuild + consolidation +
long-term archive + governance job dispatch.

Sits between FastAPI handlers (main.py routers) and the storage modules
(task_storage, memory_cache, governance_jobs, agent_keys). Handlers stay
thin: validate input, call one service, shape the response.

MEMORY_BACKEND access is lazy via `from backend import main as _main;
_main.MEMORY_BACKEND` to stay compatible with the test fixture's
importlib reload pattern.
"""
```

For each function, capture the body verbatim and rewrite cross-module deps. `dispatch_governance_job` is special: `scripts/governance_worker.py` imports it directly (`from backend.main import dispatch_governance_job`). The re-export in main.py preserves that.

- [ ] **Step 2: Delete from main.py + re-export**

```python
from backend.services import (  # noqa: F401  (re-exported for worker + tests)
    archive_active_long_term_facts,
    dispatch_governance_job,
    rebuild_memory_cache,
    run_consolidation_operation,
    store_memory_with_governance,
)
```

- [ ] **Step 3: Verify governance_worker.py still works**

Run: `uv run python -c "from backend.main import dispatch_governance_job; print(dispatch_governance_job)"`
Expected: prints `<function dispatch_governance_job at 0x...>` (re-exported from services).

- [ ] **Step 4: pytest + ruff**

Run: `uv run pytest -x -q && uv run ruff check backend tests scripts`
Expected: 186 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/services.py backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): extract business services to backend/services.py

Moves store_memory_with_governance, dispatch_governance_job,
rebuild_memory_cache, archive_active_long_term_facts, and
run_consolidation_operation into a service layer module. main.py shrinks
to mostly @app handlers + lifespan + boot.

Re-exports preserved so scripts/governance_worker.py keeps importing
dispatch_governance_job from backend.main unchanged.

main.py: ~1580 -> ~980 lines.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 15 — Split routers/

**Goal:** Move 27 `@app.<verb>` handlers from main.py into `backend/routers/*.py`, one file per domain.

**Files:**
- Create: `backend/routers/__init__.py`
- Create: `backend/routers/health.py` (~30 lines, 6 handlers)
- Create: `backend/routers/memories.py` (~120 lines, 7 handlers)
- Create: `backend/routers/tasks.py` (~150 lines, 7 handlers)
- Create: `backend/routers/governance.py` (~80 lines, 5 handlers)
- Create: `backend/routers/admin.py` (~50 lines, 3 handlers)
- Modify: `backend/main.py` (delete all @app handlers, add `app.include_router(...)` calls)

**Pattern for each router file:**

```python
# backend/routers/<domain>.py
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends

from backend.auth import verify_api_key
from backend.schemas import (...)  # only what this router needs
from backend.services import (...)  # only services this domain calls

router = APIRouter()

@router.post("/v1/<endpoint>")
def handler(payload: ..., auth: dict[str, Any] = Depends(verify_api_key)):
    ...
```

**main.py wires them up:**

```python
from backend.routers import admin, governance, health, memories, tasks

app.include_router(health.router)
app.include_router(memories.router)
app.include_router(tasks.router)
app.include_router(governance.router)
app.include_router(admin.router)
```

### Task 15.1: Create routers/__init__.py + routers/health.py

**Endpoints in health.py:**
- `GET /` (root)
- `GET /favicon.ico`
- `GET /v1/ui` (ui_index)
- `GET /v1/healthz`
- `GET /v1/runtime-topology`
- `GET /v1/metrics`

- [ ] **Step 1: Create the init file**

Write `backend/routers/__init__.py`:

```python
"""HTTP router modules grouped by domain."""
```

- [ ] **Step 2: Capture handler bodies + write health.py**

Run:
```bash
sed -n '1804,1870p' backend/main.py
sed -n '2313,2317p' backend/main.py
```

Copy bodies into `backend/routers/health.py`. Replace `@app.get(...)` with `@router.get(...)`. Imports needed: `compute_metrics`, `build_runtime_topology` from `backend.metrics`; `verify_api_key` from `backend.auth`. The `_requires_frontend_build` decorator and `ui_index` use file-system reads — keep those imports as in main.py.

- [ ] **Step 3: Delete those handlers from main.py + add include_router**

Add to top of main.py (after app = FastAPI(...)):

```python
from backend.routers import health
app.include_router(health.router)
```

- [ ] **Step 4: Run pytest**

Run: `uv run pytest tests/test_app.py -x -q`
Expected: all health/topology/metrics tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/__init__.py backend/routers/health.py backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): split routers/ part 1 — health + metrics + topology

Moves GET / favicon, /v1/ui, /v1/healthz, /v1/runtime-topology, /v1/metrics
into backend/routers/health.py. main.py uses app.include_router(health.router).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 15.2: routers/memories.py

**Endpoints:**
- `POST /v1/memories` (add_memory)
- `GET /v1/memories` (get_memories)
- `GET /v1/memories/{id}` (get_memory)
- `DELETE /v1/memories/{id}` (delete_memory)
- `POST /v1/search` (search_memories)
- `POST /v1/memory-route` (memory_route)
- `POST /v1/cache/rebuild` (cache_rebuild)

- [ ] **Step 1: Capture + write router file**

Source line ranges in current main.py: 1872-1910 (add_memory), 1912-1936 (get_memories), 1938-1945 (get_memory), 1947-1985 (search_memories), 1987-2006 (delete_memory), 2028-2047 (memory_route), 2671-end (cache_rebuild — find exact range with grep).

Imports: `MemoryCreate, SearchRequest, MemoryRouteRequest, CacheRebuildRequest` from `backend.schemas`; `route_memory` from `backend.routing`; `rebuild_memory_cache` from `backend.services`; `hybrid_search` from `backend.search_pipeline`.

- [ ] **Step 2: Replace handlers in main.py with include_router(memories.router)**

- [ ] **Step 3: pytest**

Run: `uv run pytest tests/test_app.py tests/test_search.py -x -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/routers/memories.py backend/main.py
git commit -m "refactor(backend): split routers/ part 2 — memories + search + route + cache.rebuild"
```

### Task 15.3: routers/tasks.py

**Endpoints:**
- `POST /v1/task-resolution` (task_resolution)
- `POST /v1/task-summaries` (task_summaries)
- `GET /v1/tasks` (list_tasks)
- `GET /v1/tasks/{id}` (get_task)
- `POST /v1/tasks/{id}/close` (close_task)
- `POST /v1/tasks/{id}/archive` (archive_task)
- `POST /v1/tasks/normalize` (tasks_normalize)

- [ ] **Step 1: Write routers/tasks.py**
- [ ] **Step 2: Replace in main.py**
- [ ] **Step 3: pytest**

Run: `uv run pytest tests/test_tasks.py tests/test_app.py -x -q`

- [ ] **Step 4: Commit**

```bash
git add backend/routers/tasks.py backend/main.py
git commit -m "refactor(backend): split routers/ part 3 — task lifecycle endpoints"
```

### Task 15.4: routers/governance.py

**Endpoints:**
- `POST /v1/consolidate` (consolidate)
- `POST /v1/governance/jobs` (governance_jobs_create)
- `GET /v1/governance/jobs` (governance_jobs_list)
- `GET /v1/governance/jobs/{id}` (governance_jobs_get)
- `POST /v1/governance/jobs/run-next` (governance_jobs_run_next)

- [ ] **Step 1: Write routers/governance.py**
- [ ] **Step 2: Replace in main.py**
- [ ] **Step 3: pytest**

Run: `uv run pytest tests/test_governance.py tests/test_governance_worker.py -x -q`

- [ ] **Step 4: Commit**

```bash
git add backend/routers/governance.py backend/main.py
git commit -m "refactor(backend): split routers/ part 4 — governance + consolidate"
```

### Task 15.5: routers/admin.py + final cleanup

**Endpoints:**
- `POST /v1/agent-keys` (agent_keys_create)
- `GET /v1/agent-keys` (agent_keys_list)
- `GET /v1/audit-log` (audit_log)

- [ ] **Step 1: Write routers/admin.py**
- [ ] **Step 2: Replace in main.py — should now have ZERO @app handlers**

Verify: `grep -c "^@app\." backend/main.py`
Expected: 0.

- [ ] **Step 3: Run full pytest + ruff**

Run: `uv run pytest -x -q && uv run ruff check backend tests scripts`
Expected: 186 passed, ruff clean.

- [ ] **Step 4: Verify final main.py size**

Run: `wc -l backend/main.py`
Expected: ~400 lines.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/admin.py backend/main.py
git commit -m "$(cat <<'EOF'
refactor(backend): split routers/ part 5 — admin endpoints, main.py is now thin

main.py is now ~400 lines: imports, lifespan, get_memory_backend,
app = FastAPI(...), and 5 app.include_router(...) calls. All 27
@app handlers live in backend/routers/{health,memories,tasks,governance,admin}.py.

Original 4902 lines -> 400 lines (-92%). Phases 1-15 complete.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 16 — Final verification + deploy

### Task 16.1: Local end-to-end check

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: 186 passed.

- [ ] **Step 2: Ruff**

Run: `uv run ruff check backend tests scripts`
Expected: All checks passed!

- [ ] **Step 3: Module load smoke**

Run: `uv run python -c "from backend.main import app, dispatch_governance_job, route_memory, resolve_task, fetch_tasks; print('imports ok')"`
Expected: `imports ok`.

- [ ] **Step 4: Worker import smoke**

Run: `uv run python -c "from scripts.governance_worker import _import_backend_dispatch; fn = _import_backend_dispatch(); print(fn)"`
Expected: prints tuple of three callables.

- [ ] **Step 5: Push**

```bash
git push origin main
```

### Task 16.2: VPS deploy

- [ ] **Step 1: SSH + pull**

```bash
ssh gc-jp 'cd /opt/automem && git pull --ff-only && pip install -e . && systemctl restart automem-api automem-governance-worker'
```

- [ ] **Step 2: Health check**

```bash
ssh gc-jp 'curl -s -H "X-API-Key: $ADMIN_API_KEY" http://127.0.0.1:8888/v1/healthz | head -c 200'
```

Expected: `{"ok":true,...}`.

- [ ] **Step 3: Worker log spot check**

```bash
ssh gc-jp 'journalctl -u automem-governance-worker --since "5 minutes ago" | tail -30'
```

Expected: no Python tracebacks; "claimed job" / "no pending jobs" messages.

- [ ] **Step 4: CI green**

After push, watch GitHub Actions on `main`. Expected: all 4 jobs green.

---

## Risks + Rollback

**Per-phase rollback:** each commit is atomic. If Phase N breaks tests, `git reset --hard HEAD~1` and re-think. Phases 11–14 each touch ≤2 files; Phase 15 splits into 5 sub-commits, each touching one router + main.py.

**Module-isolation regression:** if any test fails after extraction with `sqlite3.OperationalError: no such table` or `task_id not found`, the symptom is that Phase 11 missed a call site. Grep `backend/<new module>.py` for `TASK_DB_PATH` and replace.

**MEMORY_BACKEND access:** every extracted module that touches mem0 MUST use `from backend import main as _main; _main.MEMORY_BACKEND` (lazy, in-function). Do NOT do `from backend.main import MEMORY_BACKEND` at module top — that captures the value at import time and won't see test fixture's `module.MEMORY_BACKEND = FakeMemory()`.

**Worker contract:** `scripts/governance_worker.py` imports three names from `backend.main`. Re-exports in main.py keep that working — verify with the smoke test in Task 16.1 step 4.

**FastAPI route order:** `app.include_router(...)` should run *after* `app = FastAPI(...)` and after lifespan attach. Watch for import-time side effects in router modules (the routers should NOT import MEMORY_BACKEND eagerly).

---

## Summary

Total estimated commits: **8**
- Phase 11: 1 commit (sqlite path conversion)
- Phase 12: 1 commit (routing.py)
- Phase 13: 1 commit (task_storage.py)
- Phase 14: 2 commits (search_pipeline.py, services.py)
- Phase 15: 5 commits (one per router file)
- Phase 16: 0 commits (verification + deploy)

Total expected diff: -2300 lines from main.py, +2300 lines spread across 9 new modules.

Test invariant: 186 passed, ruff clean at every commit. CI green after push.
