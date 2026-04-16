from __future__ import annotations

from importlib import import_module

import pytest


pytestmark = [pytest.mark.slow, pytest.mark.serial, pytest.mark.timeout(30)]


def test_scheduler_driver_returns_enqueued_job_payload(tmp_path) -> None:
    live_backend_module = import_module("tests.support.live_backend")
    runtime_drivers = import_module("tests.support.runtime_drivers")

    with live_backend_module.running_live_backend(tmp_path) as harness:
        result = runtime_drivers.run_scheduler_enqueue(
            harness,
            idempotency_key="runtime-driver-scheduler-test",
        )

    assert result.exit_code == 0
    assert result.payload["job_type"] == "consolidate"
    assert result.payload["status"] == "pending"
    assert result.payload["job_id"]
    assert result.command[-1] == "scripts/scheduled_consolidate.py"


def test_worker_driver_returns_run_next_payload(tmp_path) -> None:
    live_backend_module = import_module("tests.support.live_backend")
    runtime_drivers = import_module("tests.support.runtime_drivers")

    with live_backend_module.running_live_backend(tmp_path) as harness:
        enqueued = runtime_drivers.run_scheduler_enqueue(
            harness,
            idempotency_key="runtime-driver-worker-test",
        )
        result = runtime_drivers.run_worker_once(harness, worker_id="runtime-test-worker")

    assert enqueued.exit_code == 0
    assert result.exit_code == 0
    assert result.payload["status"] == "processed"
    assert result.payload["worker_id"] == "runtime-test-worker"
    assert result.payload["job"]["job_id"] == enqueued.payload["job_id"]
    assert result.payload["job"]["status"] == "completed"
    assert result.command[-1] == "scripts/governance_worker.py"
