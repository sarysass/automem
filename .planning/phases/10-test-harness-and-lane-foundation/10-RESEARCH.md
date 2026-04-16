# Phase 10: Test Harness And Lane Foundation - Research

**Researched:** 2026-04-16  
**Domain:** Python/FastAPI regression harness foundation for API, worker, and scheduler flows [VERIFIED: codebase grep]  
**Confidence:** HIGH

## User Constraints

- No phase-specific `CONTEXT.md` exists for Phase 10, so the active planning constraints come from the roadmap entry, requirement IDs, and success criteria for this phase. [VERIFIED: init phase-op][VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/REQUIREMENTS.md]
- Phase 10 must satisfy `HARN-01`, `HARN-02`, and `HARN-03`, and it depends on Phase 09. [VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/REQUIREMENTS.md]
- The phase goal is a shared, isolated regression harness that boots the real backend and supports worker and scheduler entrypoints without production-only test seams. [VERIFIED: .planning/ROADMAP.md]
- The current milestone is explicitly about backend regression depth, not browser E2E expansion, broad adapter matrices, always-on real-stack CI, vanity coverage targets, or a large `backend/main.py` refactor. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: .planning/research/SUMMARY.md]

## Summary

The repo already has the right fast-lane base: `tests/conftest.py` imports `backend/main.py`, sets temporary `TASK_DB_PATH` and `HISTORY_DB_PATH`, injects a `FakeMemory`, and wraps requests in `with TestClient(...)`, which is the FastAPI-supported way to run lifespan during tests. [VERIFIED: tests/conftest.py][CITED: https://fastapi.tiangolo.com/advanced/testing-events/]

Phase 10 should keep that in-process `TestClient` path as the default fast lane and add exactly one shared live-process harness implementation for slow lane tests. [VERIFIED: tests/conftest.py][VERIFIED: .planning/research/ARCHITECTURE.md] The preferred shape in this repo is a pytest-owned child process that imports `backend.main`, injects the same `FakeMemory` before serving, binds temporary DB and lock-file paths, and then exposes a real HTTP base URL that worker and scheduler scripts can hit unchanged. [VERIFIED: tests/conftest.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

The important boundary is not “use a real network server at any cost”; it is “exercise the real backend contract without adding production-only seams.” [VERIFIED: .planning/research/PITFALLS.md] That means no test-only endpoints, no worker shortcuts hidden behind production flags, no relying on `run_inline=True` as a substitute for worker coverage, and no fixed `sleep()`-driven orchestration tests. [VERIFIED: backend/main.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py][VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

**Primary recommendation:** Prefer one reusable `tests/support/` live-backend fixture implementation with function-scoped isolated instances, register `slow` and `serial` markers, and drive worker/scheduler coverage only through the existing HTTP endpoints and script entrypoints. [VERIFIED: codebase grep][CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html][CITED: https://coverage.readthedocs.io/en/7.10.7/config.html]

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARN-01 | Maintainer can run a shared live-process test harness that boots the API with isolated temp state and deterministic test dependencies. | Use a pytest-owned live backend fixture that sets temp DB paths, explicit auth env, and injected `FakeMemory`, while reusing the real FastAPI app and lifespan. [VERIFIED: tests/conftest.py][CITED: https://fastapi.tiangolo.com/advanced/testing-events/] |
| HARN-02 | Maintainer can run worker and scheduler tests against the same isolated harness without adding test-only production endpoints. | Drive `scripts/governance_worker.py` and `scripts/scheduled_consolidate.py` as subprocesses against the harness base URL and assert results through `/governance/jobs`, `/metrics`, and `/audit-log`. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py][VERIFIED: backend/main.py] |
| HARN-03 | Maintainer can classify tests into fast and slow lanes so routine PR validation stays quick while deeper integration coverage remains available. | Register strict pytest markers, keep existing `TestClient` suites in the fast lane by default, and move live-process/script suites under `@pytest.mark.slow` with explicit commands. [VERIFIED: pyproject.toml][CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Boot isolated API harness with deterministic temp state | API / Backend | Database / Storage | The harness must boot the real FastAPI app and bind isolated SQLite paths before serving requests. [VERIFIED: tests/conftest.py][VERIFIED: backend/main.py] |
| Run worker `run-next` flows against public contracts | API / Backend | Database / Storage | The worker script is an HTTP client over `/governance/jobs/run-next`, and the queue state lives in SQLite. [VERIFIED: scripts/governance_worker.py][VERIFIED: backend/main.py] |
| Run scheduler enqueue flows against the same harness | API / Backend | Database / Storage | The scheduler script is an HTTP client over `/governance/jobs` or `/consolidate`, and job state is persisted in SQLite. [VERIFIED: scripts/scheduled_consolidate.py][VERIFIED: backend/main.py] |
| Keep cross-test state isolated | Database / Storage | API / Backend | Temp DB files and lock files are the main leak vectors across tests in this phase. [VERIFIED: tests/conftest.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py] |
| Classify fast versus slow lanes | API / Backend | — | In this repo, lane governance is owned by pytest configuration and backend-test fixture choices, not by the frontend or database layers. [VERIFIED: pyproject.toml][VERIFIED: .github/workflows/ci.yml] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pytest` | Repo line `8.4.x`; latest registry `9.0.3` published `2026-04-07`. [VERIFIED: pyproject.toml][VERIFIED: uv.lock][VERIFIED: pip index][VERIFIED: PyPI] | Test runner, fixture system, and lane selection via markers. [CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] | The repo already uses pytest, and official docs support strict marker registration for fast/slow lane governance. [VERIFIED: pyproject.toml][CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |
| `fastapi.testclient.TestClient` on repo `fastapi 0.135.2` / `httpx 0.28.1` | Existing repo base. [VERIFIED: uv.lock][VERIFIED: pyproject.toml] | Fast deterministic API integration lane with real lifespan execution. [CITED: https://fastapi.tiangolo.com/advanced/testing-events/] | This is already how backend integration tests run today, so Phase 10 should extend it rather than replace it. [VERIFIED: tests/conftest.py] |
| `pytest-cov` + `coverage[toml]` | `pytest-cov 7.1.0` published `2026-03-21`; `coverage 7.13.5` is current and already in `uv.lock`. [VERIFIED: uv.lock][VERIFIED: pip index][VERIFIED: PyPI] | Coverage across live worker/scheduler subprocesses. [CITED: https://coverage.readthedocs.io/en/7.10.7/config.html] | `coverage` added `patch = subprocess` in `7.10`, which is the cleanest way to measure child-process lanes without ad hoc bootstrap hacks. [CITED: https://coverage.readthedocs.io/en/7.10.7/config.html] |
| `pytest-timeout` | `2.4.0`, published `2025-05-05`. [VERIFIED: PyPI] | Guard slow-lane hangs caused by lock files, dead workers, or polling mistakes. [CITED: https://github.com/pytest-dev/pytest-timeout/blob/main/README.rst] | Worker and scheduler tests exercise loops and locks, so explicit timeout control is safer than relying on CI/global job timeouts. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py][CITED: https://github.com/pytest-dev/pytest-timeout/blob/main/README.rst] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `respx` | `0.23.1`, published `2026-04-08`. [VERIFIED: PyPI] | Focused `httpx` boundary mocking for failure-path unit tests. [VERIFIED: PyPI] | Use only for narrow unit coverage of outbound HTTP behavior; do not use it to fake worker/scheduler end-to-end flows. [VERIFIED: .planning/research/STACK.md][VERIFIED: .planning/research/PITFALLS.md] |
| `asgi-lifespan` | `2.1.0`, published `2023-03-28`. [VERIFIED: PyPI] | Async lifespan management when an `httpx.AsyncClient` fixture is truly needed. [VERIFIED: PyPI] | Only add if a slow-lane fixture or helper needs async client semantics; Phase 10 can stay sync-first if `TestClient` and subprocess drivers are enough. [VERIFIED: tests/conftest.py][VERIFIED: .planning/research/STACK.md] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pytest-owned child-process bootstrap that injects `FakeMemory` before serving | `uvicorn backend.main:app` CLI directly | Simpler to launch, but it cannot reuse the current deterministic fake backend setup from `tests/conftest.py` without adding new production seams. [VERIFIED: tests/conftest.py][VERIFIED: ops/systemd/automem-api.service] |
| Marker-based lane split (`slow`, `serial`) | Separate test directories or a custom runner script | Directories or wrapper scripts can work, but pytest markers are the standard minimal mechanism and fit the current repo with fewer moving parts. [CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |
| Function-scoped isolated live harness instances | Session-scoped shared mutable harness | Session scope is faster, but it increases state-leak risk before the harness API has stabilized. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py] |

**Installation:**
```bash
uv add --dev "coverage[toml]" pytest-timeout respx asgi-lifespan
```

**Version verification:** The repo already carries `pytest 8.4.2`, `pytest-cov 7.1.0`, `fastapi 0.135.2`, `httpx 0.28.1`, and `coverage 7.13.5` in `uv.lock`, while current registry checks show `pytest 9.0.3`, `fastapi 0.136.0`, and `httpx 0.28.1`. [VERIFIED: uv.lock][VERIFIED: pip index] Phase 10 should stay on the repo’s current dependency line and avoid bundling a framework upgrade into harness work. [VERIFIED: .planning/research/SUMMARY.md]

## Architecture Patterns

### System Architecture Diagram

```text
pytest fast lane
  -> tests/conftest.py
  -> import backend/main.py
  -> temp TASK_DB_PATH + HISTORY_DB_PATH + FakeMemory
  -> with TestClient(app)
  -> public API endpoints
  -> assert response + SQLite/audit/metrics state

pytest slow lane
  -> tests/support/live_backend.py fixture
  -> child process imports backend/main.py
  -> temp DB paths + temp lock files + explicit ADMIN_API_KEY + FakeMemory
  -> wait_for_http_ready(/healthz)
  -> runtime_drivers launch scheduler/worker scripts unchanged
  -> scripts hit /governance/jobs and /governance/jobs/run-next
  -> backend mutates SQLite queue/audit state
  -> wait_for_job_status / metrics / audit assertions
```

This diagram matches the repo’s existing control-plane split: the API owns queue state and governance execution, while worker and scheduler remain HTTP-only entrypoints over the backend contract. [VERIFIED: backend/main.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

### Recommended Project Structure

```text
tests/
├── conftest.py                  # shared fast-lane fixtures and env builders
├── support/
│   ├── __init__.py
│   ├── fake_memory.py           # extracted deterministic fake backend
│   ├── live_backend.py          # child-process server fixture + env wiring
│   ├── runtime_drivers.py       # subprocess wrappers for worker/scheduler scripts
│   └── waiting.py               # condition-based polling helpers
├── test_harness_foundation_live.py
├── test_runtime_entrypoints_live.py
└── ...
```

Also expect `pyproject.toml` to change for marker registration and coverage config, and expect either `README.md` or `CONTRIBUTING.md` to document the new lane commands because they currently only advertise `uv run pytest`. [VERIFIED: pyproject.toml][VERIFIED: CONTRIBUTING.md][VERIFIED: README.md]

### Pattern 1: Shared Live Backend Fixture

**What:** Build one reusable live-backend fixture implementation under `tests/support/live_backend.py`, but keep each test instance isolated with its own temp directory, temp DB files, and temp lock-file paths. [VERIFIED: tests/conftest.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**When to use:** Use it for tests that must exercise worker/scheduler scripts or any public entrypoint that requires a real HTTP base URL. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**Example:**
```python
# Source pattern: FastAPI lifespan testing docs + current tests/conftest.py
@pytest.fixture()
def live_backend(tmp_path):
    env = build_test_env(tmp_path)
    proc, base_url = start_backend_process(env)
    wait_for_http_ready(base_url, api_key=env["ADMIN_API_KEY"])
    try:
        yield {"base_url": base_url, "env": env}
    finally:
        stop_backend_process(proc)
```

The important repo-specific detail is `start_backend_process`: it should import `backend.main`, assign the same deterministic fake backend used by `tests/conftest.py`, and only then serve requests. [VERIFIED: tests/conftest.py]

### Pattern 2: Runtime Drivers Over Public Entry Points

**What:** Wrap `scripts/governance_worker.py` and `scripts/scheduled_consolidate.py` in small test helpers that launch them as subprocesses with `MEMORY_URL`, `MEMORY_API_KEY`, and temp lock-file env vars. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**When to use:** Use this for slow-lane orchestration tests; do not call backend queue helpers directly when the requirement is to verify runtime entrypoints. [VERIFIED: .planning/REQUIREMENTS.md]

**Example:**
```python
# Source pattern: current script env contracts
result = run_python_entrypoint(
    "scripts/scheduled_consolidate.py",
    env={
        **live_backend["env"],
        "MEMORY_URL": live_backend["base_url"],
        "MEMORY_API_KEY": live_backend["env"]["ADMIN_API_KEY"],
        "MEMORY_CONSOLIDATE_MODE": "enqueue",
    },
)
assert result["job_type"] == "consolidate"
```

### Pattern 3: Condition-Based Waiting

**What:** Poll the condition you care about, not a guessed sleep duration. [VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

**When to use:** Use polling for backend readiness, governance job completion, metrics visibility, and audit visibility. [VERIFIED: backend/main.py][VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

**Example:**
```python
# Source pattern: condition-based waiting guidance + existing governance endpoints
def wait_for_job_status(client, job_id, *, statuses, timeout_s=10.0, interval_s=0.1):
    deadline = time.monotonic() + timeout_s
    while True:
        response = client.get(f"/governance/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] in statuses:
            return job
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out waiting for {job_id} to reach {sorted(statuses)}")
        time.sleep(interval_s)
```

### Anti-Patterns to Avoid

- **Launching the slow lane with `uvicorn backend.main:app` directly:** it bypasses the current test-owned `FakeMemory` injection path and pushes the repo toward new production seams. [VERIFIED: tests/conftest.py][VERIFIED: ops/systemd/automem-api.service]
- **Using `run_inline=True` as worker coverage:** that exercises the API’s inline path, not the worker script contract Phase 10 is supposed to support. [VERIFIED: backend/main.py]
- **Relying on `PYTEST_CURRENT_TEST` as the auth bootstrap path for the live server:** the repo currently allows startup bypass when that env var is present, but the harness should set a real `ADMIN_API_KEY` and not depend on that loophole. [VERIFIED: backend/main.py]
- **Sharing temp DBs or lock files across tests:** both scripts derive lock files from `TASK_DB_PATH`, so reuse risks cross-test leakage and false skips. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]
- **Fixed sleeps for orchestration assertions:** this is the exact flake pattern the condition-based-waiting guidance warns against. [VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Worker/scheduler test seam | A new `/test/*` or `/worker/test-run` production endpoint | Existing `/governance/jobs` and `/governance/jobs/run-next` plus the real scripts | The backend already exposes the queue contract the scripts use in production. [VERIFIED: backend/main.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py] |
| Child-process coverage | A custom `sitecustomize` hack or bespoke env bootstrap | `[tool.coverage.run] patch = ["subprocess"]` with `parallel = true` | Official coverage docs added `subprocess` patching in `7.10`, and it is less fragile than hand-rolled startup hooks. [CITED: https://coverage.readthedocs.io/en/7.10.7/config.html] |
| Lane governance | A custom shell runner as the primary interface | Registered pytest markers with explicit commands | Marker registration is the standard pytest mechanism and keeps Phase 10 small. [CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |
| Async completion checks | Suite-local `time.sleep(1)` guesses | Shared `waiting.py` helpers that poll fresh state with a timeout | Polling makes live harness tests more reliable and faster than guessed delays. [VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md] |

**Key insight:** Phase 10 should add test-owned infrastructure around the current production contract, not new production behavior for tests to call. [VERIFIED: .planning/research/ARCHITECTURE.md][VERIFIED: .planning/research/PITFALLS.md]

## Common Pitfalls

### Pitfall 1: Breaking Deterministic Dependencies While Chasing a “Real” Server

**What goes wrong:** A live harness launches `backend.main:app` directly and accidentally pulls real mem0/Qdrant/Ollama config instead of the deterministic fake backend. [VERIFIED: tests/conftest.py][VERIFIED: backend/main.py]

**Why it happens:** The current fake backend injection happens only after import inside `tests/conftest.py`, not through an environment flag or a production endpoint. [VERIFIED: tests/conftest.py]

**How to avoid:** Move `FakeMemory` into `tests/support/fake_memory.py` and let the live server bootstrap import and assign it before serving traffic. [VERIFIED: tests/conftest.py]

**Warning signs:** A harness proposal starts from `uvicorn backend.main:app` and has no answer for deterministic memory backend injection. [VERIFIED: tests/conftest.py][VERIFIED: ops/systemd/automem-api.service]

### Pitfall 2: Calling Backend Helpers Instead of Runtime Entry Points

**What goes wrong:** The suite proves queue internals but never proves that `scripts/governance_worker.py` and `scripts/scheduled_consolidate.py` still interoperate with the real backend. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**Why it happens:** It is faster to call `/governance/jobs/run-next` through `TestClient` than to boot a live harness and launch the scripts. [VERIFIED: tests/test_backend_baseline.py]

**How to avoid:** Keep the fast queue API characterization tests, but add separate slow-lane subprocess-driver tests for the scripts. [VERIFIED: tests/test_backend_baseline.py][VERIFIED: .planning/REQUIREMENTS.md]

**Warning signs:** A Phase 10 plan mentions HARN-02 but creates no runtime-driver helper and no slow-lane script suite. [VERIFIED: .planning/REQUIREMENTS.md]

### Pitfall 3: State Leakage Through Shared DB and Lock Paths

**What goes wrong:** One slow-lane test causes the next to see leftover jobs, stale lock files, or reused audit rows. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py][VERIFIED: backend/main.py]

**Why it happens:** Both scripts derive lock files from `TASK_DB_PATH`, and the backend stores queue/audit state in SQLite files. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py][VERIFIED: backend/main.py]

**How to avoid:** Generate temp `TASK_DB_PATH`, `HISTORY_DB_PATH`, `AUTOMEM_WORKER_LOCK_FILE`, and `MEMORY_CONSOLIDATE_LOCK_FILE` per test fixture instance. [VERIFIED: tests/conftest.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**Warning signs:** A harness fixture is session-scoped before the DB/lock reset story exists, or script env vars are left at defaults. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

### Pitfall 4: Using Blind Sleeps for Queue Completion

**What goes wrong:** Slow-lane tests become flaky across machines and CI load. [VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

**Why it happens:** Worker/scheduler flows are asynchronous enough that guessed delays look convenient in the first implementation. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**How to avoid:** Centralize `wait_for_http_ready`, `wait_for_job_status`, and `wait_for_metric` helpers with explicit timeouts and descriptive failures. [VERIFIED: backend/main.py][VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

**Warning signs:** New tests include `time.sleep(...)` outside a polling helper or a documented timing-semantics test. [VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]

## Code Examples

Verified patterns from official sources:

### Register Fast/Slow Markers Strictly
```toml
# Source: pytest docs, adapted for this repo
[tool.pytest.ini_options]
addopts = "-q --strict-markers"
markers = [
  "slow: live-process harness and cross-runtime tests",
  "serial: tests that own DB/lock/process lifecycle",
]
```
[CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html]

### Enable Child-Process Coverage Cleanly
```toml
# Source: coverage.py config docs, adapted for this repo
[tool.coverage.run]
source = ["backend", "scripts", "cli"]
parallel = true
patch = ["subprocess"]
```
[CITED: https://coverage.readthedocs.io/en/7.10.7/config.html]

### Use `with TestClient(...)` for Lifespan
```python
# Source: FastAPI testing-events docs
with TestClient(app) as client:
    response = client.get("/healthz", headers={"X-API-Key": "test-admin"})
    assert response.status_code == 200
```
[CITED: https://fastapi.tiangolo.com/advanced/testing-events/]

### Bound Slow Tests With Timeouts
```python
# Source: pytest-timeout README
@pytest.mark.slow
@pytest.mark.timeout(60)
def test_worker_processes_enqueued_job(live_backend):
    ...
```
[CITED: https://github.com/pytest-dev/pytest-timeout/blob/main/README.rst]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual subprocess coverage bootstrapping with `sitecustomize` or `.pth` hacks | `coverage` built-in `[run] patch = subprocess` | Coverage `7.10` [CITED: https://coverage.readthedocs.io/en/7.10.7/config.html] | Phase 10 can measure live worker/scheduler subprocesses without custom startup glue. [CITED: https://coverage.readthedocs.io/en/7.10.7/config.html] |
| Ad hoc marker usage that only warns on mistakes | Strict marker registration in pytest config | Supported in current pytest docs; `strict` mode expanded in pytest `9.0`, while `strict_markers` remains available individually. [CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] | Lane names become enforceable, which matters once fast/slow commands are part of contributor workflow. [CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |
| One big backend suite that mixes queue characterization with API coverage | Two-lane foundation: fast `TestClient` lane plus slow live-process/runtime-entrypoint lane | This phase recommendation, driven by current repo topology. [VERIFIED: tests/conftest.py][VERIFIED: tests/test_backend_baseline.py][VERIFIED: .planning/research/ARCHITECTURE.md] | Phase 11 and Phase 12 can add deep-user and failure-recovery stories without inventing new boot logic per suite. [VERIFIED: .planning/ROADMAP.md] |

**Deprecated/outdated:**
- Treating `run_inline=True` as sufficient worker proof is outdated for this milestone because HARN-02 explicitly requires worker and scheduler tests against the shared harness. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: backend/main.py]
- Treating `uv run pytest` as the only contributor-facing command is outdated once the repo introduces fast/slow markers, because maintainers then need distinct lane commands. [VERIFIED: CONTRIBUTING.md][VERIFIED: README.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| None | All substantive factual claims in this document were verified against the codebase, current package registries, or official docs. [VERIFIED: codebase grep][VERIFIED: pip index][CITED: official docs URLs] | — | — |

## Open Questions (RESOLVED)

1. **Should Phase 10 extract `FakeMemory` into `tests/support/fake_memory.py` or duplicate it for the live harness?**
   - What we know: `FakeMemory` currently lives only in `tests/conftest.py`, and the live harness needs the same deterministic behavior before serving requests. [VERIFIED: tests/conftest.py]
   - Resolution: resolved in favor of extraction during Phase 10 so both fast and slow lanes share one deterministic backend contract, which is now captured by Plan `10-01`. [VERIFIED: tests/conftest.py][VERIFIED: .planning/phases/10-test-harness-and-lane-foundation/10-01-PLAN.md]
   - Implementation consequence: `tests/support/fake_memory.py` becomes the single source of truth, and `tests/conftest.py` plus the live harness both import it instead of duplicating behavior.

2. **Is function-scoped live harness startup cost acceptable for the first slow lane?**
   - What we know: function scope is the safest way to avoid DB/lock leakage, and the current repo has no shared live harness yet. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]
   - Resolution: resolved in favor of function scope for Phase 10, with any module or session optimization explicitly deferred until the first live suites exist and can be timed, which is reflected in Plans `10-01` and `10-02`. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py][VERIFIED: .planning/phases/10-test-harness-and-lane-foundation/10-01-PLAN.md][VERIFIED: .planning/phases/10-test-harness-and-lane-foundation/10-02-PLAN.md]
   - Implementation consequence: every live test owns its temp DB, history DB, worker lock, and consolidate lock paths, and performance tuning is not part of this phase acceptance target.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | Locked test execution and dependency install | ✓ [VERIFIED: local exec] | `0.9.26` [VERIFIED: local exec] | — |
| `python3` | Backend, pytest, and live harness child process | ✓ [VERIFIED: local exec] | `3.14.3` [VERIFIED: local exec] | — |
| `pytest` | Lane execution | ✓ [VERIFIED: local exec] | Global CLI `9.0.2`, but repo lock is `8.4.2`; use `uv run pytest` to stay on repo dependencies. [VERIFIED: local exec][VERIFIED: uv.lock] | `uv run pytest` |
| `node` / `npm` | Not required for HARN-01..03, but available for later adapter/runtime expansion | ✓ [VERIFIED: local exec] | Node `24.11.1`, npm `11.6.2` [VERIFIED: local exec] | — |

**Missing dependencies with no fallback:**
- None for Phase 10’s recommended fast and slow lanes, because the deterministic harness should continue using the fake memory backend rather than requiring Docker, Qdrant, or Ollama. [VERIFIED: tests/conftest.py][VERIFIED: .planning/research/SUMMARY.md]

**Missing dependencies with fallback:**
- None. [VERIFIED: local exec]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` on repo line `8.4.2` with `pytest-cov`; global machine CLI is newer, so use `uv run pytest`. [VERIFIED: uv.lock][VERIFIED: local exec] |
| Config file | `pyproject.toml` today; extend it for markers and coverage config in Phase 10. [VERIFIED: pyproject.toml] |
| Quick run command | `uv run pytest -m "not slow"` [CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |
| Full suite command | `uv run pytest` after markers are registered and slow-lane suites exist. [VERIFIED: .github/workflows/ci.yml][CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HARN-01 | Live backend boots with temp state, deterministic fake backend, and real lifespan | integration | `uv run pytest -m slow tests/test_harness_foundation_live.py -x` | ❌ Wave 0 |
| HARN-02 | Scheduler enqueues and worker consumes against the same live harness with no test-only endpoint | integration | `uv run pytest -m slow tests/test_runtime_entrypoints_live.py -x` | ❌ Wave 0 |
| HARN-03 | Marker-based fast/slow lane selection and isolation rules work locally | integration/config | `uv run pytest tests/test_lane_selection.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest -m "not slow"`
- **Per wave merge:** `uv run pytest -m slow tests/test_harness_foundation_live.py tests/test_runtime_entrypoints_live.py`
- **Phase gate:** Run both the fast lane and the targeted slow-lane foundation suites before `/gsd-verify-work`. [VERIFIED: .planning/ROADMAP.md]

### Wave 0 Gaps

- [ ] `tests/support/fake_memory.py` — shared deterministic backend for fast and slow lanes. [VERIFIED: tests/conftest.py]
- [ ] `tests/support/live_backend.py` — child-process server fixture and env wiring. [VERIFIED: codebase grep]
- [ ] `tests/support/runtime_drivers.py` — subprocess wrappers for worker and scheduler entrypoints. [VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]
- [ ] `tests/support/waiting.py` — condition-based polling helpers. [VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md]
- [ ] `tests/test_harness_foundation_live.py` — HARN-01 coverage. [VERIFIED: .planning/REQUIREMENTS.md]
- [ ] `tests/test_runtime_entrypoints_live.py` — HARN-02 coverage. [VERIFIED: .planning/REQUIREMENTS.md]
- [ ] `tests/test_lane_selection.py` — HARN-03 lane verification. [VERIFIED: .planning/REQUIREMENTS.md]
- [ ] `pyproject.toml` marker registration and coverage config. [VERIFIED: pyproject.toml][CITED: https://doc.pytest.org/en/latest/explanation/goodpractices.html][CITED: https://coverage.readthedocs.io/en/7.10.7/config.html]
- [ ] Dev dependency install: `uv add --dev "coverage[toml]" pytest-timeout respx asgi-lifespan` [VERIFIED: pyproject.toml][VERIFIED: PyPI]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Use real `X-API-Key` auth in the live harness with explicit `ADMIN_API_KEY`; do not rely on startup bypass behavior alone. [VERIFIED: backend/main.py] |
| V3 Session Management | no | The backend uses API keys, not server-side sessions, for the paths this phase exercises. [VERIFIED: backend/main.py] |
| V4 Access Control | yes | Keep testing through existing scope checks and auth-bound endpoints, especially worker/scheduler admin paths. [VERIFIED: backend/main.py][VERIFIED: tests/test_identity_e2e.py] |
| V5 Input Validation | yes | FastAPI/Pydantic request models validate `/governance/jobs`, `/governance/jobs/run-next`, and `/consolidate` payloads. [VERIFIED: backend/main.py] |
| V6 Cryptography | no | Phase 10 should not introduce custom crypto; it only consumes existing API-key flows. [VERIFIED: backend/main.py] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Harness accidentally boots with auth bootstrap bypass only | Spoofing / Elevation | Set explicit `ADMIN_API_KEY` in the child-process env and assert authenticated `/healthz` readiness. [VERIFIED: backend/main.py] |
| Shared DB or lock files leak between tests | Tampering / DoS | Per-test temp DB paths and per-test lock-file env vars. [VERIFIED: tests/conftest.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py] |
| Fake worker proof via inline API path | Repudiation / Tampering | Test worker/scheduler through their real scripts and public queue endpoints only. [VERIFIED: backend/main.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py] |
| Hung worker/scheduler tests hide in CI until job timeout | DoS | Add `pytest-timeout` and explicit polling timeouts at the test layer. [CITED: https://github.com/pytest-dev/pytest-timeout/blob/main/README.rst][VERIFIED: ~/.codex/skills/condition-based-waiting/SKILL.md] |

## Sources

### Primary (HIGH confidence)

- Repo codebase: `tests/conftest.py`, `tests/test_backend_baseline.py`, `tests/test_governance_worker.py`, `tests/test_scheduled_consolidate.py`, `scripts/governance_worker.py`, `scripts/scheduled_consolidate.py`, `backend/main.py`, `pyproject.toml`, `.github/workflows/ci.yml`. [VERIFIED: codebase grep]
- Project planning docs: `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/research/SUMMARY.md`, `.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`. [VERIFIED: planning docs]
- Pytest docs on strict markers and strict mode: https://doc.pytest.org/en/latest/explanation/goodpractices.html [CITED]
- FastAPI docs on lifespan testing: https://fastapi.tiangolo.com/advanced/testing-events/ [CITED]
- Coverage.py config reference for `patch = subprocess`: https://coverage.readthedocs.io/en/7.10.7/config.html [CITED]
- `pytest-timeout` README via Context7: https://github.com/pytest-dev/pytest-timeout/blob/main/README.rst [CITED]
- Current package/version verification via `pip index` and PyPI JSON for `pytest`, `pytest-cov`, `coverage`, `pytest-timeout`, `respx`, and `asgi-lifespan`. [VERIFIED: pip index][VERIFIED: PyPI]

### Secondary (MEDIUM confidence)

- `.planning/codebase/TESTING.md` and `.planning/codebase/CONVENTIONS.md` for current repo test patterns and contributor norms. [VERIFIED: planning docs]
- `~/.codex/skills/condition-based-waiting/SKILL.md` for the polling pattern applied to this repo’s live harness design. [VERIFIED: skill read]

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - current repo usage, registry checks, and official docs all agree on the recommended pytest/TestClient/coverage shape. [VERIFIED: codebase grep][VERIFIED: pip index][CITED: official docs URLs]
- Architecture: HIGH - the repo already exposes the exact API, worker, and scheduler boundaries this phase needs, so the recommendation is additive rather than speculative. [VERIFIED: backend/main.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]
- Pitfalls: HIGH - the main risks are directly visible in the current codebase: fake-backend injection location, inline-vs-worker drift, temp-path leakage, and polling flake. [VERIFIED: tests/conftest.py][VERIFIED: backend/main.py][VERIFIED: scripts/governance_worker.py][VERIFIED: scripts/scheduled_consolidate.py]

**Research date:** 2026-04-16  
**Valid until:** 2026-05-16 for repo-structure guidance; refresh package-version checks sooner if dependency work starts later. [VERIFIED: pip index]
