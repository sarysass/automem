---
phase: 10-test-harness-and-lane-foundation
audited_at: 2026-04-17T01:24:16+0800
audit_state: B
status: secured
asvs_level: 1
asvs_level_note: "Inferred because no <config> block was present in the Phase 10 artifacts."
block_on: unspecified
threats_total: 9
threats_closed: 9
threats_open: 0
unregistered_flags: 0
---

# Phase 10 Security Audit

Artifact-driven mitigation audit for Phase 10 (`10-test-harness-and-lane-foundation`).

- Audit state: `B` (artifact review backed by fresh pytest verification)
- ASVS level: `1` (inferred; Phase 10 artifacts contained no `<config>` block)
- Block-on policy: not specified in the available artifacts

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-10-01-01 | T/I | mitigate | CLOSED | `tests/support/live_backend.py:46-68` builds per-test temp env with explicit `TASK_DB_PATH`, `HISTORY_DB_PATH`, `AUTOMEM_WORKER_LOCK_FILE`, and `MEMORY_CONSOLIDATE_LOCK_FILE`; `tests/test_harness_foundation_live.py:33-41` asserts the runtime paths stay inside the test temp dir. |
| T-10-01-02 | E | mitigate | CLOSED | `tests/support/live_backend.py:52-53,145` sets `ADMIN_API_KEY=test-admin`; `tests/test_harness_foundation_live.py:12-19,25-33` proves `/healthz` returns `401` without `X-API-Key` and `200` with the real header; `backend/main.py:3867-3870,3946-3949` keeps `/healthz` behind `verify_api_key`. |
| T-10-01-03 | S | mitigate | CLOSED | `tests/support/live_backend.py:80-90,93-105` dynamically imports `backend/main.py`, assigns `module.MEMORY_BACKEND = FakeMemory()`, and runs `module.ensure_task_db()` before serving traffic; `tests/support/fake_memory.py:6-67` provides the injected fake backend. |
| T-10-02-01 | T | mitigate | CLOSED | `tests/support/runtime_drivers.py:41-48,74-93,114-153` launches the committed scripts as subprocesses with explicit `MEMORY_URL`, `MEMORY_API_KEY`, and per-test lock files; `tests/test_runtime_drivers.py:11-25,28-45` asserts the invoked commands are `scripts/scheduled_consolidate.py` and `scripts/governance_worker.py`. |
| T-10-02-02 | D | mitigate | CLOSED | `tests/support/waiting.py:10-47` remains the shared polling helper; `tests/test_runtime_entrypoints_live.py:9,12,81-99,126-167` uses `wait_for_condition(...)` for queue-state polling; `tests/test_harness_foundation_live.py:9`, `tests/test_runtime_drivers.py:8`, and `tests/test_runtime_entrypoints_live.py:12` add `pytest.mark.timeout(30)`; `pyproject.toml:16-21` and `uv.lock:69,87,1191` wire `pytest-timeout`; `tests/test_lane_selection.py:45-50` guards the timeout markers from drifting away. |
| T-10-02-03 | I | mitigate | CLOSED | `tests/test_runtime_entrypoints_live.py:27-52,81-100,141-168` asserts state only through `/governance/jobs/{job_id}`, `/governance/jobs`, `/metrics`, and `/audit-log`; `tests/support/live_backend.py:167-170` provides a function-scoped fixture and `tests/test_runtime_entrypoints_live.py:59-65,107-113` boots a fresh harness per test. |
| T-10-03-01 | R | mitigate | CLOSED | `pyproject.toml:24-34` enables `--strict-markers`, registers `slow` and `serial`, and enables subprocess coverage; `tests/test_lane_selection.py:28-55` parses `pyproject.toml` and the validation contract to guard lane-selection drift, including timeout-marker coverage. |
| T-10-03-02 | D | mitigate | CLOSED | `.github/workflows/ci.yml:18-23` keeps the default PR pytest step on `uv run pytest -m "not slow"`. |
| T-10-03-03 | T | mitigate | CLOSED | `CONTRIBUTING.md:27-39,47-63` publishes the exact fast-lane and slow-lane commands from the Phase 10 validation contract. |

## Fresh Verification

- `uv run pytest tests/test_lane_selection.py -x` -> `3 passed in 0.01s`
- `uv run pytest -m slow tests/test_harness_foundation_live.py tests/test_runtime_entrypoints_live.py tests/test_runtime_drivers.py -x` -> `6 passed in 4.91s`

## Accepted Risks Log

None.

## Transfer Evidence

None.

## Unregistered Flags

None. No `## Threat Flags` section was present in:

- `10-01-SUMMARY.md`
- `10-02-SUMMARY.md`
- `10-03-SUMMARY.md`
- `10-VERIFICATION.md`

## Audit Summary

- Closed threats: `9/9`
- Open threats: `0/9`
- Main change since the prior audit: `T-10-02-02` is now closed because the slow live suites still reuse `tests/support/waiting.py` and now also carry explicit pytest timeout enforcement backed by the `pytest-timeout` dependency.
