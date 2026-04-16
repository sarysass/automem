# Technology Stack Research: v1.1 Testing Depth & Real-World Regression

**Project:** automem
**Milestone:** v1.1 Testing Depth & Real-World Regression
**Researched:** 2026-04-16
**Scope:** New testing capabilities only
**Overall confidence:** HIGH for pytest/FastAPI/coverage/Qdrant/test harness guidance; MEDIUM for the exact mem0 test seam because current mem0 docs do not expose a drop-in local-mode path for automem's existing `Memory.from_config(...)` setup.

## Executive Recommendation

Keep the current `pytest` + `fastapi.testclient.TestClient` + temporary SQLite foundation. It already matches the backend-centered design and should stay the default for unit and most integration coverage.

The missing piece is not a new test runner. It is a new **live-process harness** that starts the real FastAPI app, then drives `scripts/governance_worker.py` and `scripts/scheduled_consolidate.py` against it over HTTP with isolated temp databases, lock files, and env files. That gives automem real end-to-end regression coverage for API -> queue -> worker -> scheduler -> task/search state transitions without turning every PR into a full infrastructure bring-up.

Add only a small set of focused libraries:

- `coverage[toml]` for subprocess coverage
- `pytest-timeout` for deadlock and wait-loop failures
- `respx` for `httpx` boundary mocking in unit tests
- `asgi-lifespan` for async app-level tests when `httpx.AsyncClient` is useful

Use `testcontainers` only for an opt-in Qdrant contract lane. Do **not** make Docker + Ollama mandatory for the default suite.

## Current Baseline

The current codebase already has the right core primitives:

- `pytest` is the repo-wide backend test runner.
- `tests/conftest.py` builds the app with temp SQLite paths and swaps in `FakeMemory`.
- `tests/test_identity_e2e.py` shows strong request-level scope tests with `TestClient`.
- `tests/test_governance_worker.py` and `tests/test_scheduled_consolidate.py` already validate worker/scheduler logic, but only with fake clients or direct module calls.
- CI currently runs `uv run pytest` only; there is no subprocess coverage, timeout guard, or live-process E2E lane.

That means automem does **not** need a testing rewrite. It needs one more layer on top of the existing stack.

## Recommended Stack Additions

### Core additions

| Technology | Version | Purpose | Why it fits automem | Integration cost |
|------------|---------|---------|----------------------|------------------|
| `coverage[toml]` | `>=7.13,<8.0` | Collect coverage from live API, worker, and scheduler subprocesses | `pytest-cov` 7.x no longer handles subprocess coverage for you; automem's new realistic tests will launch Python child processes | Low |
| `pytest-timeout` | `>=2.4,<3.0` | Fail fast on lock hangs, wait loops, and dead worker tests | automem has lock files, poll loops, retries, and queue leases; silent hangs are a real regression mode | Low |
| `respx` | `>=0.23,<0.24` | Mock outbound `httpx` traffic with request matching | better fit than handwritten fake clients for `backend/governance/judge.py`, `scripts/`, and adapter-side HTTP failure tests | Low |
| `asgi-lifespan` | `>=2.1,<3.0` | Trigger FastAPI lifespan in async app tests | useful when a test needs `httpx.AsyncClient` but still wants startup/shutdown behavior | Low |

### Optional addition

| Technology | Version | Purpose | When to use it | Integration cost |
|------------|---------|---------|----------------|------------------|
| `testcontainers` | `>=4.14,<5.0` | Start disposable Qdrant for a narrow contract suite | only for an opt-in `docker` lane that checks the real mem0 + Qdrant storage path | Medium |

### Keep as-is

| Technology | Current line | Recommendation | Why |
|------------|--------------|----------------|-----|
| `pytest` | `>=8.4,<9.0` in repo today | Keep the 8.4 line for this milestone | latest PyPI is `9.0.3`, but upgrading the core runner while adding a new harness adds risk with little value |
| `pytest-cov` | `>=7.0,<8.0` in repo today | Keep it, but pair it with direct `coverage` config | still the right pytest integration layer |
| `mem0ai` | currently `1.0.7` in repo | Do not mix this milestone with a mem0 major upgrade | latest PyPI is `2.0.0`; that is a separate compatibility project, not a testing task |

## Recommended Dependency Layout

Use the repo's existing `dependency-groups` pattern instead of inventing a second package manager flow.

```toml
[dependency-groups]
dev = [
  "mcp>=1.26,<2.0",
  "pytest>=8.4,<9.0",
  "pytest-cov>=7.0,<8.0",
  "coverage[toml]>=7.13,<8.0",
  "pytest-timeout>=2.4,<3.0",
  "respx>=0.23,<0.24",
  "asgi-lifespan>=2.1,<3.0",
]

docker = [
  "testcontainers>=4.14,<5.0",
]
```

Why separate `docker`:

- most automem regressions are in auth, governance, task lifecycle, queueing, retries, and search filtering
- those can be proven without requiring every developer and every CI PR job to have Docker + Qdrant + Ollama ready
- the real vector-store lane is useful, but it should be explicit and opt-in

## Harness Architecture

### 1. Unit layer

Keep pure rule and failure-recovery tests in-process.

Use this layer for:

- governance rules
- task classification edge cases
- auth and scope helpers
- retry counters, lease math, idempotency-key generation
- malformed upstream response handling

Recommended tools:

- `pytest`
- `monkeypatch`
- `respx` for outbound `httpx` calls

Why:

- fastest feedback
- easiest place to exhaust edge conditions
- no port management or subprocess cleanup needed

### 2. Integration layer

Keep the current `TestClient` model and expand it.

Use this layer for:

- route-level auth and scope checks
- task and memory lifecycle behavior
- search filtering and history toggles
- API behavior where `FakeMemory` or a deterministic test backend is sufficient

Recommended tools:

- `pytest`
- `fastapi.testclient.TestClient`
- temp SQLite fixtures

Why:

- FastAPI's official testing path is still the right fit for most backend routes
- `with TestClient(app)` already triggers lifespan correctly

### 3. Live-process E2E layer

Add a new layer that launches the real runtime as subprocesses:

1. start the API with isolated env and temp paths
2. seed state through real HTTP calls
3. run `scripts/scheduled_consolidate.py`
4. run `scripts/governance_worker.py`
5. poll job/task/search endpoints until the expected end state appears

Use this layer for:

- deep-user workflows spanning more than one process
- queue + worker retry behavior
- scheduler enqueue behavior
- lock-file skip behavior
- runtime topology and health checks
- evidence that the real scripts and real env wiring behave together

Recommended tools:

- `pytest`
- `httpx.Client`
- `subprocess.Popen`
- `pytest-timeout`
- `coverage[toml]`

This is the most important new testing capability for the milestone.

### 4. Optional Qdrant contract layer

Keep this narrow. Do not make it the center of the milestone.

Use this layer only for:

- proving that automem's mem0/Qdrant config still boots
- proving that real storage schema/index assumptions did not drift
- catching breakage in the production storage integration path

Recommended tools:

- `testcontainers`
- real Qdrant image
- dedicated `@pytest.mark.docker`

Important constraint:

Qdrant's Python client supports local mode (`QdrantClient(":memory:")` or `path=...`), but automem currently initializes mem0 with a host/port Qdrant config and Ollama embedder settings. That means Qdrant local mode is **not** a drop-in replacement for the current app path. If automem later adds a test-only memory backend seam, local mode becomes more attractive. Until then, use either:

- a deterministic in-repo test backend for default E2E
- or a real containerized Qdrant lane for the storage contract

## Required Fixture Strategy

### Shared fixture modules

Add dedicated support modules instead of growing `tests/conftest.py` into a second monolith.

Recommended layout:

```text
tests/
  conftest.py
  support/
    runtime.py
    processes.py
    memory_backend.py
    factories.py
    polling.py
  e2e/
    test_deep_user_regression.py
    test_worker_recovery.py
    test_scheduler_enqueue.py
    test_search_and_task_lifecycle.py
```

### Fixtures to add

| Fixture | Responsibility | Why it matters |
|---------|----------------|----------------|
| `runtime_dir` | temp directory for dbs, logs, locks, env files | keeps each E2E isolated |
| `free_port` | choose an unused port for the API | prevents flaky collisions in local/dev/CI runs |
| `runtime_env` | materialize an env file with all per-test settings | lets API/worker/scheduler share one authoritative config |
| `api_server` | start/stop the real API process and wait for `/healthz` | this is the core E2E entrypoint |
| `api_client` | real `httpx.Client` against the live server | exercises real HTTP behavior |
| `run_worker_once` | run the worker in one-shot mode and capture stdout/stderr | proves queue consumption and job completion |
| `run_scheduler_once` | run `scheduled_consolidate.py` with the same env file | proves enqueue and lock behavior |
| `wait_for_job_status` | poll until `pending/completed/failed` | removes arbitrary sleeps |
| `seed_project_key` / `seed_memory` / `seed_task` | high-level factories over real HTTP | keeps tests readable and scenario-focused |

### Condition-based waiting

Do not use fixed `sleep(...)` calls as the main synchronization strategy.

Poll for observable conditions instead:

- `/healthz` returning `200`
- `/governance/jobs/{id}` showing `completed` or `failed`
- `/tasks` or `/search` reflecting the expected state

This is especially important for worker, lease, and retry tests.

## Environment Changes Needed

### 1. Add a test-selectable memory backend hook

This is the most important code-level change needed to unlock real subprocess E2E without standing up Ollama on every run.

Recommended shape:

- add an env-configured import hook such as `AUTOMEM_MEMORY_BACKEND_FACTORY`
- or add a simple built-in flag like `AUTOMEM_TEST_MEMORY_BACKEND=deterministic`

Why:

- current tests patch `module.MEMORY_BACKEND = FakeMemory()` after importing `backend/main.py`
- that works in-process, but not for a separately launched API subprocess
- without this hook, realistic E2E either becomes brittle monkeypatching or forces full mem0 + Qdrant + Ollama for all runs

The deterministic backend should preserve the semantics automem cares about for this milestone:

- add/get/search/delete
- metadata preservation
- predictable record IDs
- basic search matching

It does **not** need to emulate vector math perfectly.

### 2. Add subprocess coverage wiring

At minimum:

- `COVERAGE_PROCESS_START`
- a `.pth` or `sitecustomize.py` startup hook that calls `coverage.process_startup()`
- `[tool.coverage.run]` in `pyproject.toml`
- `coverage combine` in CI for subprocess data

Recommended config direction:

```toml
[tool.coverage.run]
branch = true
parallel = true
dynamic_context = "test_function"

[tool.coverage.report]
show_missing = true
skip_covered = false
```

### 3. Give each live test isolated paths

Every live E2E should get unique values for:

- `TASK_DB_PATH`
- `HISTORY_DB_PATH`
- `AUTOMEM_WORKER_LOCK_FILE`
- `MEMORY_CONSOLIDATE_LOCK_FILE`
- `BIND_PORT`
- `MEMORY_URL`
- `AUTOMEM_ENV_FILE`

This is necessary even before considering parallel execution.

### 4. Add test markers

Recommended markers:

- `unit`
- `integration`
- `e2e`
- `slow`
- `docker`

This allows CI to keep a fast PR lane and a heavier opt-in lane.

## CI Recommendations

### Pull request lane

Run on every PR:

- `uv run pytest -m "not docker"`
- coverage with subprocess combine enabled

This lane should include:

- all unit tests
- current TestClient integration tests
- a small number of live-process E2E tests covering the highest-value workflows

### Opt-in or nightly lane

Run separately:

- `uv run pytest -m docker`

This lane can require Docker and start Qdrant with `testcontainers`.

Do **not** require Ollama model pulls in the default CI path. That would test external model availability more than automem's control-plane behavior.

## What NOT To Add

### Do not add `pytest-xdist` yet

Why not:

- automem uses SQLite files, lock files, ports, and module-level globals
- `pytest-xdist` helps only after resource isolation is mature
- adding parallelism before that will create flaky failures and hide real regressions behind shared-state races

Revisit only after:

- every live test has unique paths and ports
- the backend no longer depends on import-time globals for test substitution
- the suite is stable in serial

### Do not add browser E2E tooling for this milestone

No Playwright, Cypress, or Selenium for v1.1.

Why not:

- the milestone is backend-centered
- the new risk is process wiring, queueing, auth, retries, and scheduler behavior
- browser tests would increase maintenance cost without improving confidence on the control-plane failures this milestone targets

### Do not make Docker + Qdrant + Ollama the default local or PR workflow

Why not:

- mem0's documented local open-source path assumes Qdrant plus Ollama
- that is too heavy for the main regression lane
- model startup and download issues would create noisy failures unrelated to automem logic

Use a deterministic backend for the main E2E lane and keep real infrastructure in a narrow contract lane.

### Do not add cassette/snapshot recording for LLM or embedder behavior

No VCR-style "golden response" layer for this milestone.

Why not:

- it freezes external behavior rather than proving automem's internal guarantees
- it creates brittle approvals for text variance
- automem's regression value is in routing, scoping, task lifecycle, retries, and failure handling

## Recommended Test Scenarios The Stack Unlocks

These are the kinds of scenarios the proposed stack is meant to support:

1. Deep-user project-scoped workflow
   - create bound key
   - store long-term memory
   - write task summary
   - enqueue consolidation
   - run worker once
   - assert tasks/search/history end state over real HTTP

2. Failure-recovery workflow
   - enqueue a job that fails due to mocked upstream `httpx` failure
   - assert attempts increment and status returns to `pending`
   - rerun worker with success path
   - assert job completes and state is recoverable

3. Scheduler lock workflow
   - create a lock file
   - run `scheduled_consolidate.py`
   - assert machine-readable skip output
   - remove lock and rerun
   - assert job enqueue succeeds

4. Search plus lifecycle regression
   - seed multiple facts and task records
   - run a consolidation/reclassification path
   - assert active vs superseded visibility and task archive normalization through the real API

## Final Recommendation

For v1.1, the right stack is:

- keep `pytest`, `pytest-cov`, `TestClient`, temp SQLite
- add `coverage[toml]`, `pytest-timeout`, `respx`, and `asgi-lifespan`
- add a deterministic subprocess-friendly memory backend hook in `backend/main.py`
- add a live-process E2E harness around the real API, worker, and scheduler
- keep `testcontainers` optional for a narrow Qdrant contract lane

That gives automem stronger proof of real behavior without turning a testing milestone into an infrastructure migration.

## Sources

### Official docs and package sources

- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- FastAPI lifespan testing: https://fastapi.tiangolo.com/advanced/testing-events/
- FastAPI async tests: https://fastapi.tiangolo.com/advanced/async-tests/
- coverage.py subprocess handling: https://coverage.readthedocs.io/en/latest/subprocess.html
- coverage.py configuration: https://coverage.readthedocs.io/en/latest/config.html
- Qdrant Python client local mode: https://github.com/qdrant/qdrant-client
- Testcontainers Python docs: https://testcontainers-python.readthedocs.io/
- RESPX docs: https://lundberg.github.io/respx/
- pytest-xdist docs: https://pytest-xdist.readthedocs.io/
- PyPI package metadata for current versions checked on 2026-04-16:
  - https://pypi.org/project/pytest/
  - https://pypi.org/project/pytest-cov/
  - https://pypi.org/project/coverage/
  - https://pypi.org/project/pytest-timeout/
  - https://pypi.org/project/respx/
  - https://pypi.org/project/testcontainers/
  - https://pypi.org/project/qdrant-client/
  - https://pypi.org/project/mem0ai/

### Confidence notes

- HIGH: FastAPI testing approach, coverage subprocess requirement, Qdrant local-mode capability, testcontainers lifecycle usage, xdist caveats
- MEDIUM: exact shape of the mem0 test seam, because current mem0 docs still emphasize host/port Qdrant plus Ollama and do not document a clean local-mode substitution path for automem's current config
