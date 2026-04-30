"""Admin HTTP handlers (agent-keys CRUD + audit-log read)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.agent_keys import create_agent_key, list_api_keys
from backend.audit_log import fetch_audit_log
from backend.auth import require_scope, verify_api_key
from backend.schemas import AgentKeyCreateRequest

router = APIRouter()


@router.post("/v1/agent-keys")
def agent_keys_create(payload: AgentKeyCreateRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    if "admin" not in payload.scopes and not payload.user_id:
        raise HTTPException(status_code=400, detail="Non-admin API keys require user_id")
    return create_agent_key(
        agent_id=payload.agent_id,
        label=payload.label,
        scopes=payload.scopes,
        user_id=payload.user_id,
        project_ids=payload.project_ids,
        token=payload.token,
    )


@router.get("/v1/agent-keys")
def agent_keys_list(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    return {"keys": list_api_keys()}


@router.get("/v1/audit-log")
def audit_log(
    limit: int = 50,
    event_type: Optional[str] = None,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "admin")
    return {"events": fetch_audit_log(limit=limit, event_type=event_type)}
