from __future__ import annotations

from typing import Any, Optional

from .judge import govern_memory_candidate


def govern_consolidation_candidate(*, text: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    decision = govern_memory_candidate(
        text=text,
        metadata={**(metadata or {}), "route_origin": "consolidate"},
    )
    return decision.model_dump()


def should_run_offline_judge(*, text: str, metadata: Optional[dict[str, Any]] = None) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    meta = metadata or {}
    if str(meta.get("domain") or "") == "task":
        return True
    return len(normalized) >= 40
