"""Pydantic request/response schemas for the automem HTTP API.

Extracted from backend.main during the main.py-split refactor. backend.main
re-exports every name here so existing test suites and adapters that do
`from backend.main import ConsolidateRequest` keep working unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class MemoryCreate(BaseModel):
    messages: List[Message]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    project_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    infer: bool = True


class SearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    project_id: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    limit: int = 10
    include_history: bool = False


class TaskResolutionRequest(BaseModel):
    user_id: str
    message: str
    agent_id: Optional[str] = None
    project_id: Optional[str] = None
    assistant_output: Optional[str] = None
    session_id: Optional[str] = None
    channel: Optional[str] = None


class TaskSummaryWriteRequest(BaseModel):
    user_id: str
    agent_id: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    progress: Optional[str] = None
    blocker: Optional[str] = None
    next_action: Optional[str] = None
    message: Optional[str] = None
    assistant_output: Optional[str] = None
    session_id: Optional[str] = None
    channel: Optional[str] = None


class MemoryRouteRequest(BaseModel):
    user_id: str
    message: str
    agent_id: Optional[str] = None
    project_id: Optional[str] = None
    assistant_output: Optional[str] = None
    session_id: Optional[str] = None
    channel: Optional[str] = None
    client_hints: Optional[Dict[str, Any]] = None


class ConsolidateRequest(BaseModel):
    dry_run: bool = True
    dedupe_long_term: bool = True
    archive_closed_tasks: bool = True
    normalize_task_state: bool = True
    prune_non_work_archived: bool = False
    archive_work_without_memory_active: bool = True
    prune_work_without_memory_archived: bool = False
    user_id: Optional[str] = None
    project_id: Optional[str] = None


class CacheRebuildRequest(BaseModel):
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None


class AgentKeyCreateRequest(BaseModel):
    agent_id: str
    label: str
    scopes: List[str]
    user_id: Optional[str] = None
    project_ids: Optional[List[str]] = None
    token: Optional[str] = None


class TaskLifecycleRequest(BaseModel):
    reason: Optional[str] = None


class TaskNormalizeRequest(BaseModel):
    dry_run: bool = True
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    archive_non_work_active: bool = True
    prune_non_work_archived: bool = False
    archive_work_without_memory_active: bool = True
    prune_work_without_memory_archived: bool = False


class GovernanceJobCreateRequest(BaseModel):
    job_type: Literal["consolidate"]
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    max_attempts: int = 3
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    run_inline: bool = False


class GovernanceJobRunRequest(BaseModel):
    worker_id: Optional[str] = None
    job_types: Optional[List[str]] = None
    lease_seconds: int = 300


__all__ = [
    "AgentKeyCreateRequest",
    "CacheRebuildRequest",
    "ConsolidateRequest",
    "GovernanceJobCreateRequest",
    "GovernanceJobRunRequest",
    "MemoryCreate",
    "MemoryRouteRequest",
    "Message",
    "SearchRequest",
    "TaskLifecycleRequest",
    "TaskNormalizeRequest",
    "TaskResolutionRequest",
    "TaskSummaryWriteRequest",
]
