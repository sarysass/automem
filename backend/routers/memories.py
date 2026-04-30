"""Memory CRUD + search + route + cache-rebuild HTTP handlers.

See backend/routers/health.py docstring for the app.state.main_module
pattern that lets handlers call get_memory_backend() / normalize_text() /
ensure_memory_item_access() on the active main module instance under the
per-test importlib reload pattern in tests/conftest.py.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.audit_log import write_audit
from backend.auth import (
    enforce_agent_identity,
    enforce_payload_project_identity,
    enforce_project_identity,
    enforce_user_identity,
    merge_project_id_into_filters,
    merge_project_id_into_metadata,
    require_scope,
    verify_api_key,
)
from backend.memory_cache import delete_cached_memory
from backend.routing import route_memory
from backend.schemas import (
    CacheRebuildRequest,
    MemoryCreate,
    MemoryRouteRequest,
    SearchRequest,
)
from backend.search_pipeline import hybrid_search
from backend.services import rebuild_memory_cache, store_memory_with_governance

router = APIRouter()


def _main(request: Request):
    return request.app.state.main_module


@router.post("/v1/memories")
def add_memory(request: Request, payload: MemoryCreate, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "store")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    enforce_payload_project_identity(auth, payload)
    if not any([payload.user_id, payload.agent_id, payload.run_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required")
    payload.agent_id = enforce_agent_identity(auth, payload.agent_id)
    payload.metadata = merge_project_id_into_metadata(payload.project_id, payload.metadata)
    result = store_memory_with_governance(
        messages=[m.model_dump() for m in payload.messages],
        user_id=payload.user_id,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        metadata=payload.metadata,
        infer=payload.infer,
        memory_backend=_main(request).get_memory_backend(),
    )
    event_type = "memory_skip" if result.get("status") == "skipped" else "memory_add"
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=payload.agent_id,
        event_type=event_type,
        user_id=payload.user_id,
        task_id=payload.run_id,
        detail={
            "metadata": payload.metadata or {},
            "infer": payload.infer,
            "status": result.get("status", "stored"),
            "reason": result.get("reason"),
            "fact_status": result.get("fact_status"),
            "fact_action": result.get("fact_action"),
            "fact_key": result.get("fact_key"),
            "superseded_memory_ids": result.get("superseded_memory_ids") or [],
            "conflicts_with": result.get("conflicts_with") or [],
        },
    )
    return result


@router.get("/v1/memories")
def get_memories(
    request: Request,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    project_id: Optional[str] = None,
    auth: dict[str, Any] = Depends(verify_api_key),
):
    require_scope(auth, "search")
    user_id = enforce_user_identity(auth, user_id)
    project_id = enforce_project_identity(auth, project_id)
    if not any([user_id, run_id, agent_id]):
        raise HTTPException(status_code=400, detail="At least one identifier is required")
    params = {k: v for k, v in {"user_id": user_id, "run_id": run_id, "agent_id": agent_id}.items() if v is not None}
    main = _main(request)
    result = main.get_memory_backend().get_all(**params)
    if project_id is None:
        return result
    raw_items = result.get("results", []) if isinstance(result, dict) else result
    filtered = [
        item
        for item in raw_items
        if main.normalize_text(str((item.get("metadata") or {}).get("project_id") or "")) == project_id
    ]
    return {"results": filtered}


@router.get("/v1/memories/{memory_id}")
def get_memory(request: Request, memory_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    main = _main(request)
    item = main.get_memory_backend().get(memory_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Memory not found")
    return main.ensure_memory_item_access(auth, item)


@router.post("/v1/search")
def search_memories(request: Request, payload: SearchRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    payload.project_id = enforce_project_identity(auth, payload.project_id)
    payload.filters = merge_project_id_into_filters(payload.project_id, payload.filters)
    result = hybrid_search(
        payload.query,
        user_id=payload.user_id,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        filters=payload.filters,
        limit=payload.limit,
        include_history=payload.include_history,
        memory_backend=_main(request).get_memory_backend(),
    )
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="search",
        user_id=payload.user_id,
        project_id=(payload.filters or {}).get("project_id") if payload.filters else None,
        route=None,
        detail={
            "query": payload.query,
            "meta": result.get("meta", {}),
            "top_matches": [
                {
                    "source_memory_id": item.get("source_memory_id"),
                    "matched_by": item.get("matched_by"),
                    "matched_fields": item.get("matched_fields"),
                    "status": item.get("status"),
                }
                for item in result.get("results", [])[:5]
            ],
        },
    )
    return result


@router.delete("/v1/memories/{memory_id}")
def delete_memory(request: Request, memory_id: str, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "forget")
    main = _main(request)
    item = main.get_memory_backend().get(memory_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Memory not found")
    item = main.ensure_memory_item_access(auth, item)
    main.get_memory_backend().delete(memory_id=memory_id)
    delete_cached_memory(memory_id)
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="memory_delete",
        user_id=item.get("user_id"),
        project_id=(item.get("metadata") or {}).get("project_id"),
        detail={"memory_id": memory_id},
    )
    return {"message": "deleted"}


@router.post("/v1/memory-route")
def memory_route(payload: MemoryRouteRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "route")
    payload.user_id = enforce_user_identity(auth, payload.user_id)
    enforce_payload_project_identity(auth, payload)
    payload.agent_id = enforce_agent_identity(auth, payload.agent_id)
    result = route_memory(payload)
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=payload.agent_id,
        event_type="memory_route",
        user_id=payload.user_id,
        project_id=payload.project_id,
        task_id=(result.get("task") or {}).get("task_id"),
        route=result.get("route"),
        detail={"message": payload.message, "reason": result.get("reason")},
    )
    return result


@router.post("/v1/cache/rebuild")
def cache_rebuild(request: Request, payload: CacheRebuildRequest, auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "admin")
    rebuilt = rebuild_memory_cache(
        user_id=payload.user_id,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        memory_backend=_main(request).get_memory_backend(),
    )
    result = {
        "rebuilt": rebuilt,
        "user_id": payload.user_id,
        "run_id": payload.run_id,
        "agent_id": payload.agent_id,
    }
    write_audit(
        actor_type=auth["actor_type"],
        actor_label=auth.get("actor_label"),
        actor_agent_id=auth.get("agent_id"),
        event_type="cache_rebuild",
        user_id=payload.user_id,
        detail=result,
    )
    return result
