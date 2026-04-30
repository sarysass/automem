"""Governance + consolidation HTTP handlers.

See backend/routers/health.py docstring for the app.state.main_module
pattern that lets handlers call get_memory_backend() / normalize_text()
on the active main module instance under the per-test importlib reload
pattern in tests/conftest.py.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.audit_log import write_audit
from backend.auth import (
    enforce_project_identity,
    enforce_user_identity,
    require_scope,
    verify_api_key,
)
from backend.governance_jobs import (
    GOVERNANCE_JOB_STATUS_COMPLETED,
    claim_governance_job_by_id,
    claim_next_governance_job,
    enqueue_governance_job,
    fetch_governance_job,
    list_governance_jobs,
)
from backend.schemas import (
    ConsolidateRequest,
    GovernanceJobCreateRequest,
    GovernanceJobRunRequest,
)
from backend.services import dispatch_governance_job, run_consolidation_operation

router = APIRouter()


def _main(request: Request):
    return request.app.state.main_module


@router.post("/v1/consolidate")
def consolidate(request: Request, payload: ConsolidateRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    result = run_consolidation_operation(
        payload, runtime_path="api_inline", memory_backend=_main(request).get_memory_backend()
    )
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="consolidate",
        detail=result,
    )
    return result


@router.post("/v1/governance/jobs")
def governance_jobs_create(request: Request, payload: GovernanceJobCreateRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    payload.project_id = enforce_project_identity(auth, payload.project_id)
    if payload.job_type == "consolidate":
        consolidate_payload = ConsolidateRequest(**payload.payload)
        consolidate_payload.user_id = payload.user_id or consolidate_payload.user_id
        consolidate_payload.project_id = payload.project_id or consolidate_payload.project_id
        payload_data = consolidate_payload.model_dump()
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported governance job type: {payload.job_type}")
    job = enqueue_governance_job(
        job_type=payload.job_type,
        payload=payload_data,
        user_id=payload.user_id,
        project_id=payload.project_id,
        idempotency_key=payload.idempotency_key,
        max_attempts=payload.max_attempts,
        created_by=auth.get("actor_label") or auth.get("agent_id") or auth["actor_type"],
    )
    if payload.run_inline and job.get("status") != GOVERNANCE_JOB_STATUS_COMPLETED:
        worker_id = f"inline-{auth.get('actor_label') or auth['actor_type']}"
        claimed = claim_governance_job_by_id(
            job_id=str(job["job_id"]),
            worker_id=worker_id,
            lease_seconds=300,
        )
        if claimed and claimed["job_id"] == job["job_id"]:
            job = dispatch_governance_job(
                claimed, worker_id=worker_id, memory_backend=_main(request).get_memory_backend()
            )
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="governance_job_enqueue",
        user_id=payload.user_id,
        project_id=payload.project_id,
        detail={
            "job_id": job["job_id"],
            "job_type": job["job_type"],
            "status": job["status"],
            "idempotency_key": job.get("idempotency_key"),
            "run_inline": payload.run_inline,
            "deduplicated": job.get("deduplicated", False),
        },
    )
    return job


@router.get("/v1/governance/jobs")
def governance_jobs_list(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "admin")
    return {"jobs": list_governance_jobs(status=status, job_type=job_type, limit=limit)}


@router.get("/v1/governance/jobs/{job_id}")
def governance_jobs_get(job_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    job = fetch_governance_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Governance job not found")
    return job


@router.post("/v1/governance/jobs/run-next")
def governance_jobs_run_next(request: Request, payload: GovernanceJobRunRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    main = _main(request)
    worker_id = main.normalize_text(payload.worker_id or auth.get("agent_id") or auth.get("actor_label") or "governance-worker")
    claimed = claim_next_governance_job(
        worker_id=worker_id,
        job_types=payload.job_types,
        lease_seconds=payload.lease_seconds,
    )
    if not claimed:
        return {"status": "idle", "worker_id": worker_id}
    job = dispatch_governance_job(claimed, worker_id=worker_id, memory_backend=main.get_memory_backend())
    return {
        "status": "processed",
        "worker_id": worker_id,
        "job": job,
    }
