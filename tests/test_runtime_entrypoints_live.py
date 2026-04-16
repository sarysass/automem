from __future__ import annotations

from importlib import import_module
from typing import Any

import httpx
import pytest

from tests.support.waiting import wait_for_condition


pytestmark = [pytest.mark.slow, pytest.mark.serial]


def seed_duplicate_long_term_memory(client: httpx.Client, *, text: str, user_id: str) -> None:
    payload = {
        "messages": [{"role": "user", "content": text}],
        "user_id": user_id,
        "infer": False,
        "metadata": {"domain": "long_term", "category": "project_context"},
    }
    for _ in range(2):
        response = client.post("/memories", json=payload)
        assert response.status_code == 200, response.text


def fetch_job(client: httpx.Client, job_id: str) -> dict[str, Any] | None:
    response = client.get(f"/governance/jobs/{job_id}")
    assert response.status_code in {200, 404}, response.text
    if response.status_code == 404:
        return None
    return response.json()


def fetch_listed_job(client: httpx.Client, job_id: str) -> dict[str, Any] | None:
    response = client.get("/governance/jobs", params={"job_type": "consolidate", "limit": 20})
    assert response.status_code == 200, response.text
    jobs = response.json()["jobs"]
    return next((job for job in jobs if job["job_id"] == job_id), None)


def fetch_governance_metrics(client: httpx.Client) -> dict[str, Any]:
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    return response.json()["metrics"]["governance_jobs"]


def find_audit_event(client: httpx.Client, *, event_type: str, job_id: str) -> dict[str, Any] | None:
    response = client.get("/audit-log", params={"event_type": event_type, "limit": 20})
    assert response.status_code == 200, response.text
    events = response.json()["events"]
    return next((event for event in events if event.get("detail", {}).get("job_id") == job_id), None)


def test_scheduler_enqueue_creates_pending_job_visible_over_http(tmp_path) -> None:
    live_backend_module = import_module("tests.support.live_backend")
    runtime_drivers = import_module("tests.support.runtime_drivers")

    with live_backend_module.running_live_backend(tmp_path) as live_backend:
        with httpx.Client(
            base_url=live_backend.base_url,
            headers=live_backend.auth_headers,
            timeout=5.0,
            trust_env=False,
        ) as client:
            seed_duplicate_long_term_memory(
                client,
                text="Acme Corp keeps a durable roadmap",
                user_id="user-runtime-enqueue",
            )

            scheduler_result = runtime_drivers.run_scheduler_enqueue(
                live_backend,
                idempotency_key="runtime-entrypoints-enqueue",
            ).require_success()

            assert scheduler_result.payload["job_type"] == "consolidate"
            assert scheduler_result.payload["status"] == "pending"
            job_id = scheduler_result.payload["job_id"]

            job = wait_for_condition(
                lambda: fetch_job(client, job_id),
                description=f"governance job {job_id} to appear",
            )
            assert job["job_id"] == job_id
            assert job["status"] == "pending"

            listed_job = wait_for_condition(
                lambda: fetch_listed_job(client, job_id),
                description=f"governance job {job_id} in list endpoint",
            )
            assert listed_job["job_id"] == job_id
            assert listed_job["status"] == "pending"

            enqueue_event = wait_for_condition(
                lambda: find_audit_event(client, event_type="governance_job_enqueue", job_id=job_id),
                description=f"governance enqueue audit for {job_id}",
            )
            assert enqueue_event["detail"]["job_id"] == job_id
            assert enqueue_event["detail"]["status"] == "pending"


def test_worker_run_next_processes_job_and_updates_metrics_and_audit(tmp_path) -> None:
    live_backend_module = import_module("tests.support.live_backend")
    runtime_drivers = import_module("tests.support.runtime_drivers")

    with live_backend_module.running_live_backend(tmp_path) as live_backend:
        with httpx.Client(
            base_url=live_backend.base_url,
            headers=live_backend.auth_headers,
            timeout=5.0,
            trust_env=False,
        ) as client:
            seed_duplicate_long_term_memory(
                client,
                text="Acme Corp keeps a durable roadmap",
                user_id="user-runtime-worker",
            )

            scheduler_result = runtime_drivers.run_scheduler_enqueue(
                live_backend,
                idempotency_key="runtime-entrypoints-worker",
            ).require_success()
            job_id = scheduler_result.payload["job_id"]

            job = wait_for_condition(
                lambda: fetch_job(client, job_id),
                description=f"governance job {job_id} to appear",
            )
            assert job["status"] == "pending"

            worker_result = runtime_drivers.run_worker_once(
                live_backend,
                worker_id="runtime-entrypoints-worker",
            ).require_success()

            assert worker_result.payload["status"] == "processed"
            assert worker_result.payload["worker_id"] == "runtime-entrypoints-worker"
            assert worker_result.payload["job"]["job_id"] == job_id

            completed_job = wait_for_condition(
                lambda: _completed_job(client, job_id),
                description=f"governance job {job_id} completion",
            )
            assert completed_job["status"] == "completed"
            assert completed_job["result"]["runtime_path"] == "governance_worker"
            assert completed_job["result"]["duplicate_long_term_count"] >= 1

            governance_metrics = wait_for_condition(
                lambda: _completed_governance_metrics(client),
                description="governance metrics to show completed consolidate job",
            )
            assert governance_metrics["completed"] >= 1
            assert governance_metrics["by_type"]["consolidate"] >= 1

            complete_event = wait_for_condition(
                lambda: find_audit_event(client, event_type="governance_job_complete", job_id=job_id),
                description=f"governance completion audit for {job_id}",
            )
            assert complete_event["detail"]["job_id"] == job_id
            assert complete_event["detail"]["runtime_path"] == "governance_worker"

            consolidate_event = wait_for_condition(
                lambda: find_audit_event(client, event_type="consolidate", job_id=job_id),
                description=f"consolidate audit for {job_id}",
            )
            assert consolidate_event["detail"]["job_id"] == job_id
            assert consolidate_event["detail"]["runtime_path"] == "governance_worker"


def _completed_job(client: httpx.Client, job_id: str) -> dict[str, Any] | None:
    job = fetch_job(client, job_id)
    if job is None:
        return None
    if job["status"] != "completed":
        return None
    return job


def _completed_governance_metrics(client: httpx.Client) -> dict[str, Any] | None:
    metrics = fetch_governance_metrics(client)
    if metrics["completed"] < 1:
        return None
    if metrics["by_type"].get("consolidate", 0) < 1:
        return None
    return metrics
