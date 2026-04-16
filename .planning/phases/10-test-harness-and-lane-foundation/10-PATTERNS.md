# Phase 10: Test Harness And Lane Foundation - Pattern Map

**Mapped:** 2026-04-16  
**Files analyzed:** 10  
**Analogs found:** 9 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `tests/conftest.py` | test | request-response | `tests/conftest.py` | exact |
| `tests/support/__init__.py` | utility | transform | `backend/__init__.py` | exact |
| `tests/support/fake_memory.py` | utility | CRUD | `tests/conftest.py` | exact |
| `tests/support/live_backend.py` | utility | request-response | `tests/conftest.py` | role-match |
| `tests/support/runtime_drivers.py` | utility | event-driven | `scripts/governance_worker.py` | partial |
| `tests/support/waiting.py` | utility | request-response | none | no-analog |
| `tests/test_harness_foundation_live.py` | test | request-response | `tests/test_backend_baseline.py` | exact |
| `tests/test_runtime_entrypoints_live.py` | test | event-driven | `tests/test_governance_worker.py` | role-match |
| `pyproject.toml` | config | transform | `pyproject.toml` | exact |
| `CONTRIBUTING.md` | config | transform | `CONTRIBUTING.md` | exact |

`README.md` is an alternate documentation target explicitly allowed by `10-RESEARCH.md`; if the planner prefers broader user-facing command docs, copy command-list formatting from `README.md:41-71`.

## Pattern Assignments

### `tests/conftest.py` (test, request-response)

**Analog:** `tests/conftest.py`

**Imports + shared fake dependency pattern** (`tests/conftest.py:1-15`)
```python
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


class FakeMemory:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
```

**Fixture bootstrap pattern** (`tests/conftest.py:74-103`)
```python
@pytest.fixture()
def backend_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module_path = Path(__file__).resolve().parents[1] / "backend" / "main.py"
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    ...
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))

    spec = importlib.util.spec_from_file_location(f"automem_backend_{tmp_path.name}", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MEMORY_BACKEND = FakeMemory()
    module.ensure_task_db()
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture()
def client(backend_module):
    with TestClient(backend_module.app) as test_client:
        yield test_client
```

**Auth header fixture pattern** (`tests/conftest.py:106-108`)
```python
@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-admin"}
```

Copy this file's current order and naming. Phase 10 should extend it, not replace it.

---

### `tests/support/__init__.py` (utility, transform)

**Analog:** `backend/__init__.py`

**Minimal package marker pattern** (`backend/__init__.py:1`)
```python
"""automem backend package."""
```

Keep `tests/support/__init__.py` equally minimal; do not add side effects here.

---

### `tests/support/fake_memory.py` (utility, CRUD)

**Analog:** `tests/conftest.py`

**Class body to extract directly** (`tests/conftest.py:12-71`)
```python
class FakeMemory:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def _extract_text(self, messages: Any) -> str:
        if isinstance(messages, str):
            return messages
        if isinstance(messages, list):
            parts: list[str] = []
            for item in messages:
                if isinstance(item, dict):
                    parts.append(str(item.get("content", "")))
                else:
                    parts.append(str(getattr(item, "content", "")))
            return "\n".join(part for part in parts if part)
        return str(messages)

    def add(self, messages: Any, **params: Any) -> dict[str, Any]:
        memory_id = f"mem_{len(self.records) + 1}"
        ...
        self.records[memory_id] = record
        return {"id": memory_id, "results": [record]}

    def get_all(self, **params: Any) -> dict[str, Any]:
        ...

    def search(self, query: str, **params: Any) -> dict[str, Any]:
        ...

    def get(self, memory_id: str) -> dict[str, Any]:
        return self.records[memory_id]

    def delete(self, memory_id: str) -> None:
        self.records.pop(memory_id, None)
```

**Usage handoff pattern** (`tests/conftest.py:89-95`)
```python
spec = importlib.util.spec_from_file_location(f"automem_backend_{tmp_path.name}", module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.MEMORY_BACKEND = FakeMemory()
module.ensure_task_db()
```

Planner note: move the class verbatim into `tests/support/fake_memory.py`, then import it back into `tests/conftest.py` and the live harness bootstrap.

---

### `tests/support/live_backend.py` (utility, request-response)

**Primary analog:** `tests/conftest.py`

**Environment + dynamic import pattern** (`tests/conftest.py:75-97`)
```python
def backend_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module_path = Path(__file__).resolve().parents[1] / "backend" / "main.py"
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    ...
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))

    spec = importlib.util.spec_from_file_location(f"automem_backend_{tmp_path.name}", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MEMORY_BACKEND = FakeMemory()
    module.ensure_task_db()
    yield module
```

**Secondary analog:** `backend/main.py`

**Readiness/auth endpoint to poll** (`backend/main.py:3946-3958`)
```python
@app.get("/healthz")
@app.get("/v1/healthz")
def healthz(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    return {
        "ok": True,
        "llm_model": CONFIG["llm"]["config"]["model"],
        "embed_model": CONFIG["embedder"]["config"]["model"],
        "qdrant": f"{CONFIG['vector_store']['config']['host']}:{CONFIG['vector_store']['config']['port']}",
        "task_db": str(TASK_DB_PATH),
        "runtime": build_runtime_topology(),
        "metrics": compute_metrics(),
    }
```

**Auth contract to respect** (`backend/main.py:3867-3894`)
```python
async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    if api_key is None:
        raise HTTPException(status_code=401, detail="X-API-Key header is required")
    if ADMIN_API_KEY and secrets.compare_digest(api_key, ADMIN_API_KEY):
        return {
            "actor_type": "admin",
            "actor_label": "admin",
            ...
            "is_admin": True,
        }
    ...
```

**Test-side readiness assertion style** (`tests/test_backend_baseline.py:32-41`)
```python
def test_missing_api_key_requires_header(client):
    response = client.get("/healthz")
    assert response.status_code == 401
    assert response.json()["detail"] == "X-API-Key header is required"


def test_invalid_api_key_is_rejected(client):
    response = client.get("/healthz", headers={"X-API-Key": "invalid-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"
```

Planner note: bootstrap the live server with the same env and fake backend as `tests/conftest.py`, but probe it over real HTTP using `/healthz` plus the normal `X-API-Key` header path.

---

### `tests/support/runtime_drivers.py` (utility, event-driven)

**Primary analog:** `scripts/governance_worker.py`

**Worker env/client contract** (`scripts/governance_worker.py:35-53`)
```python
def build_base_url() -> str:
    configured = os.environ.get("MEMORY_URL")
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    port = os.environ.get("BIND_PORT", "8888")
    return f"http://{host}:{port}"


def build_client() -> httpx.Client:
    api_key = os.environ.get("MEMORY_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing MEMORY_API_KEY or ADMIN_API_KEY")
    return httpx.Client(
        base_url=build_base_url(),
        headers={"X-API-Key": api_key},
        timeout=120.0,
        trust_env=False,
    )
```

**Worker entrypoint contract** (`scripts/governance_worker.py:56-121`)
```python
def build_lock_path() -> Path:
    configured = os.environ.get("AUTOMEM_WORKER_LOCK_FILE")
    if configured:
        return Path(configured)
    return Path(os.environ.get("TASK_DB_PATH", ...)).with_suffix(".worker.lock")


def run_once(client: Any, *, worker_id: str) -> dict[str, Any]:
    response = client.post(
        "/governance/jobs/run-next",
        json={
            "worker_id": worker_id,
            "lease_seconds": max(30, int(os.environ.get("AUTOMEM_WORKER_LEASE_SECONDS", "300"))),
        },
    )
    if response.status_code != 200:
        raise RuntimeError(...)
    return response.json()


def main() -> int:
    load_runtime_env()
    poll_seconds = max(1.0, float(os.environ.get("AUTOMEM_WORKER_POLL_SECONDS", "5")))
    once = (os.environ.get("AUTOMEM_WORKER_ONCE") or "true").strip().lower() in {"1", "true", "yes", "on"}
    with single_worker_lock(build_lock_path()) as acquired:
        if not acquired:
            print(json.dumps({"status": "skipped", "reason": "lock_exists"}, ensure_ascii=False))
            return 0
        with build_client() as client:
            while True:
                result = run_once(client, worker_id=build_worker_id())
                print(json.dumps(result, ensure_ascii=False))
                if once or result.get("status") == "idle":
                    break
                time.sleep(poll_seconds)
```

**Secondary analog:** `scripts/scheduled_consolidate.py`

**Scheduler payload + result contract** (`scripts/scheduled_consolidate.py:100-205`)
```python
def build_payload() -> dict[str, Any]:
    return {
        "dry_run": env_flag("MEMORY_CONSOLIDATE_DRY_RUN", False),
        ...
        "user_id": os.environ.get("MEMORY_CONSOLIDATE_USER_ID") or None,
        "project_id": os.environ.get("MEMORY_CONSOLIDATE_PROJECT_ID") or None,
    }


def run_consolidation(client: Any, payload: dict[str, Any]) -> dict[str, Any]:
    attempts = max(1, int(os.environ.get("MEMORY_CONSOLIDATE_ATTEMPTS", "3")))
    retry_delay = max(0.0, float(os.environ.get("MEMORY_CONSOLIDATE_RETRY_DELAY_SECONDS", "1")))
    mode = build_mode()
    ...
    for attempt in range(1, attempts + 1):
        response = client.post(path, json=body)
        if response.status_code == 200:
            data = response.json()
            return validate_inline_result(data) if mode == "inline" else validate_job_result(data)
        ...
        if attempt < attempts:
            time.sleep(retry_delay)


def main() -> int:
    load_runtime_env()
    payload = build_payload()
    with single_run_lock(build_lock_path()) as acquired:
        if not acquired:
            print(json.dumps({"status": "skipped", "reason": "lock_exists"}, ensure_ascii=False))
            return 0
        with build_client() as client:
            result = run_consolidation(client, payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0
```

**Test assertion shape to preserve** (`tests/test_governance_worker.py:23-38`, `tests/test_scheduled_consolidate.py:77-93`)
```python
def test_run_once_posts_to_run_next(worker_module):
    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs/run-next"
            assert json["worker_id"] == "worker-a"
            return FakeResponse()


def test_run_consolidation_rejects_non_200(scheduled_module):
    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs"
            assert json["payload"]["dry_run"] is False
            return FakeResponse()
```

Planner note: runtime drivers should launch the real scripts, but they should treat these env vars, stdout JSON payloads, and lock-file conventions as the compatibility contract.

---

### `tests/support/waiting.py` (utility, request-response)

**Analog:** none

There is no existing shared polling helper in the repo. Implement this as a new helper module around already-exposed backend endpoints rather than inventing test-only seams.

**Nearest public-status endpoints** (`backend/main.py:3946-3958`, `backend/main.py:4723-4784`)
```python
@app.get("/healthz")
def healthz(...):
    return {"ok": True, ...}


@app.get("/governance/jobs/{job_id}")
def governance_jobs_get(job_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    job = fetch_governance_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Governance job not found")
    return job


@app.get("/audit-log")
def audit_log(...):
    require_scope(auth, "admin")
    return {"events": fetch_audit_log(limit=limit, event_type=event_type)}
```

**Assertions that the helper should eventually drive** (`tests/test_backend_baseline.py:1889-1927`, `tests/test_backend_baseline.py:1993-1997`)
```python
processed = client.post(
    "/governance/jobs/run-next",
    headers=auth_headers,
    json={"worker_id": "worker-a"},
)
assert processed.status_code == 200, processed.text
...
fetched = client.get(f"/governance/jobs/{queued_payload['job_id']}", headers=auth_headers)
assert fetched.status_code == 200, fetched.text
assert fetched.json()["status"] == "completed"

audit = client.get("/v1/audit-log?limit=5&event_type=memory_route", headers=auth_headers)
assert audit.status_code == 200, audit.text
assert len(audit.json()["events"]) >= 1
```

Planner note: centralize `wait_for_http_ready`, `wait_for_job_status`, and any audit/metric waiters here; keep `time.sleep(...)` inside the helper only.

---

### `tests/test_harness_foundation_live.py` (test, request-response)

**Analog:** `tests/test_backend_baseline.py`

**Assertion style for HTTP contract checks** (`tests/test_backend_baseline.py:32-41`)
```python
def test_missing_api_key_requires_header(client):
    response = client.get("/healthz")
    assert response.status_code == 401
    assert response.json()["detail"] == "X-API-Key header is required"


def test_invalid_api_key_is_rejected(client):
    response = client.get("/healthz", headers={"X-API-Key": "invalid-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"
```

**Metrics/runtime assertions to reuse** (`tests/test_backend_baseline.py:1784-1887`)
```python
metrics = client.get("/metrics", headers=auth_headers)
assert metrics.status_code == 200, metrics.text
payload = metrics.json()["metrics"]
assert payload["events"]["memory_route"] >= 1

response = client.get("/runtime-topology", headers=auth_headers)
assert response.status_code == 200, response.text
payload = response.json()
assert payload["runtime"]["api"]["background_submission_endpoint"] == "/governance/jobs"
assert "/governance/jobs/run-next" in payload["runtime"]["worker"]["run_next_endpoint"]
```

**Governance queue contract** (`tests/test_backend_baseline.py:1889-1927`)
```python
enqueued = client.post(
    "/governance/jobs",
    headers=auth_headers,
    json={
        "job_type": "consolidate",
        "payload": {"dry_run": False, "user_id": "user-a"},
        "user_id": "user-a",
        "idempotency_key": "consolidate:user-a:test",
    },
)
assert enqueued.status_code == 200, enqueued.text
...
fetched = client.get(f"/governance/jobs/{queued_payload['job_id']}", headers=auth_headers)
assert fetched.status_code == 200, fetched.text
assert fetched.json()["status"] == "completed"
```

Planner note: keep the same direct assertion style and response-shape checks, but point them at the live harness base URL instead of `TestClient`.

---

### `tests/test_runtime_entrypoints_live.py` (test, event-driven)

**Primary analog:** `tests/test_governance_worker.py`

**Worker request-path expectations** (`tests/test_governance_worker.py:23-38`)
```python
def test_run_once_posts_to_run_next(worker_module):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "idle", "worker_id": "worker-a"}

    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs/run-next"
            assert json["worker_id"] == "worker-a"
            return FakeResponse()

    result = worker_module.run_once(FakeClient(), worker_id="worker-a")
    assert result["status"] == "idle"
```

**Worker lock/skip expectation** (`tests/test_governance_worker.py:41-65`)
```python
lock_path = tmp_path / "worker.lock"
lock_path.write_text("busy")

monkeypatch.setenv("AUTOMEM_WORKER_LOCK_FILE", str(lock_path))
monkeypatch.setattr(worker_module, "load_runtime_env", lambda: None)
...
exit_code = worker_module.main()

assert exit_code == 0
assert json.loads(capsys.readouterr().out) == {"status": "skipped", "reason": "lock_exists"}
```

**Secondary analog:** `tests/test_scheduled_consolidate.py`

**Scheduler enqueue + lock expectations** (`tests/test_scheduled_consolidate.py:77-93`, `tests/test_scheduled_consolidate.py:166-188`)
```python
def test_run_consolidation_rejects_non_200(scheduled_module):
    class FakeClient:
        def post(self, path: str, json: dict[str, object]):
            assert path == "/governance/jobs"
            assert json["payload"]["dry_run"] is False
            return FakeResponse()

    with pytest.raises(RuntimeError, match="500"):
        scheduled_module.run_consolidation(FakeClient(), {"dry_run": False})


lock_path = tmp_path / "scheduled.lock"
lock_path.write_text("busy")
monkeypatch.setenv("MEMORY_CONSOLIDATE_LOCK_FILE", str(lock_path))
...
assert json.loads(capsys.readouterr().out) == {"status": "skipped", "reason": "lock_exists"}
```

**Live API verification target** (`tests/test_backend_baseline.py:1893-1927`)
```python
enqueued = client.post("/governance/jobs", headers=auth_headers, json={...})
assert enqueued.status_code == 200, enqueued.text
processed = client.post("/governance/jobs/run-next", headers=auth_headers, json={"worker_id": "worker-a"})
assert processed.status_code == 200, processed.text
assert processed.json()["job"]["status"] == "completed"
```

Planner note: this new suite should preserve today's unit-level expectations for worker/scheduler entrypoints, then add live harness assertions against the resulting queue, metrics, and audit state.

---

### `pyproject.toml` (config, transform)

**Analog:** `pyproject.toml`

**Existing TOML style to extend** (`pyproject.toml:16-25`)
```toml
[dependency-groups]
dev = [
  "mcp>=1.26,<2.0",
  "pytest>=8.4,<9.0",
  "pytest-cov>=7.0,<8.0",
]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

Planner note: keep the current compact TOML style and extend this exact `tool.pytest.ini_options` block for strict markers. There is no existing `[tool.coverage.*]` section yet, so coverage subprocess config is a new subsection, not a copy target.

---

### `CONTRIBUTING.md` (config, transform)

**Analog:** `CONTRIBUTING.md`

**Development command formatting** (`CONTRIBUTING.md:20-37`)
```md
## 本地开发

uv sync --all-groups
uv run pytest

## 提交前检查

至少完成：

uv run pytest
uv run python -m py_compile backend/main.py cli/memory scripts/scheduled_consolidate.py scripts/install_adapter.py
cd frontend && npm test && npm run build
...
```

Planner note: add lane-specific pytest commands here using the existing Chinese prose + fenced shell block style.

**Alternate broader docs target:** `README.md:41-71`
```md
## 快速开始

uv sync --all-groups
cp backend/.env.example backend/.env
uv run pytest

## 常用命令

...
python scripts/scheduled_consolidate.py
python scripts/governance_worker.py
```

Use `README.md` instead if the planner wants fast/slow lane commands visible to all repo users, not just contributors.

## Shared Patterns

### Deterministic Backend Bootstrap
**Sources:** `tests/conftest.py:74-103`, `tests/conftest.py:12-71`  
**Apply to:** `tests/conftest.py`, `tests/support/fake_memory.py`, `tests/support/live_backend.py`
```python
monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
...
spec = importlib.util.spec_from_file_location(f"automem_backend_{tmp_path.name}", module_path)
module = importlib.util.module_from_spec(spec)
...
module.MEMORY_BACKEND = FakeMemory()
module.ensure_task_db()
```

### Real Auth Path, Not Test-Only Bypass
**Sources:** `backend/main.py:3867-3894`, `tests/conftest.py:106-108`, `backend/main.py:1936-1937`  
**Apply to:** live harness helpers and all live-lane tests
```python
async def verify_api_key(api_key: Optional[str] = Depends(api_key_header)):
    if api_key is None:
        raise HTTPException(status_code=401, detail="X-API-Key header is required")
    if ADMIN_API_KEY and secrets.compare_digest(api_key, ADMIN_API_KEY):
        return {"actor_type": "admin", ...}


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": "test-admin"}


def auth_bootstrap_bypass_enabled() -> bool:
    return ALLOW_INSECURE_NOAUTH or "PYTEST_CURRENT_TEST" in os.environ
```

Phase 10 research explicitly says not to rely on the `PYTEST_CURRENT_TEST` bypass for the live server; set `ADMIN_API_KEY` and send real headers.

### Script Runtime Contract
**Sources:** `scripts/governance_worker.py:35-121`, `scripts/scheduled_consolidate.py:36-205`  
**Apply to:** `tests/support/runtime_drivers.py`, `tests/test_runtime_entrypoints_live.py`
```python
configured = os.environ.get("MEMORY_URL")
api_key = os.environ.get("MEMORY_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
...
return Path(os.environ.get("TASK_DB_PATH", ...)).with_suffix(".worker.lock")
...
print(json.dumps({"status": "skipped", "reason": "lock_exists"}, ensure_ascii=False))
```

### Observe Results Through Public API Endpoints
**Sources:** `backend/main.py:3946-3958`, `backend/main.py:4422-4426`, `backend/main.py:4723-4784`, `tests/test_backend_baseline.py:1889-1927`, `tests/test_backend_baseline.py:1993-1997`  
**Apply to:** live harness tests and wait helpers
```python
metrics = client.get("/metrics", headers=auth_headers)
assert metrics.status_code == 200, metrics.text

fetched = client.get(f"/governance/jobs/{queued_payload['job_id']}", headers=auth_headers)
assert fetched.status_code == 200, fetched.text
assert fetched.json()["status"] == "completed"

audit = client.get("/v1/audit-log?limit=5&event_type=memory_route", headers=auth_headers)
assert audit.status_code == 200, audit.text
```

### Pytest Lane Config Style
**Source:** `pyproject.toml:23-25`  
**Apply to:** `pyproject.toml`
```toml
[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

Add `--strict-markers` and marker registrations in this existing section instead of introducing a second pytest config location.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `tests/support/waiting.py` | utility | request-response | The repo has live endpoints to poll, but no existing shared polling helper module or reusable wait loop in tests. Implement it as a new helper around `/healthz`, `/governance/jobs/{job_id}`, `/metrics`, and `/audit-log`. |

## Metadata

**Analog search scope:** `tests/`, `scripts/`, `backend/`, repo-root `pyproject.toml`, `README.md`, `CONTRIBUTING.md`  
**Files scanned:** 10 primary analog files plus repo-wide `rg` searches for fixture, auth, lock, endpoint, and marker patterns  
**Pattern extraction date:** 2026-04-16
