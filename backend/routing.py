"""Hot-path routing decisions: where does an inbound memory belong?

Three pure-ish helpers extracted from backend.main:

- route_memory: top-level decision (long_term / task / mixed / drop) for a
  MemoryRouteRequest, combining heuristics with the LLM judge_route call.
- task_candidate_score: jaccard + boost scoring of a single existing task
  vs. an inbound message. Used by resolve_task to pick the best match.
- resolve_task: turns a TaskResolutionRequest into either
  match_existing_task / propose_new_task / no_task.

Module-isolation pitfall (read tests/conftest.py):
The test suite re-imports backend/main.py via importlib.spec_from_file_location
under a synthetic module name `automem_backend_<tmp>`. That fixture instance
is NOT the canonical `backend.main`. So eagerly importing module-level
constants (MEMORY_BACKEND, TASK_DB_PATH, fetch_tasks, normalize_text, etc.)
from backend.main at the top of THIS file would bind to the canonical
backend.main and ignore the per-test fixture entirely — leading to "stale
TASK_DB_PATH" / "MEMORY_BACKEND is None" failures.

Fix: any reference back to symbols still living in main.py is resolved
lazily inside the function body via `from backend import main as _main`.
By the time any of these functions runs, both backend.main (canonical)
and the per-test re-import have finished module init, and the lazy
lookup picks up whatever module the call site is actually using.

Symbols accessed via _main.X (still in main.py):
- _main.fetch_tasks (Phase 13 will move to backend.task_storage)
- _main.normalize_text (small utility, stays in main.py for now)
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.long_term import (
    extract_long_term_entries,
    looks_task_worthy,
    strip_shared_memories,
)
from backend.schemas import (
    MemoryRouteRequest,
    TaskResolutionRequest,
    TaskSummaryWriteRequest,
)
from backend.tasks import (
    derive_task_summary,
    derive_task_title,
    evaluate_task_materialization,
    extract_task_lookup_subject,
    is_task_lookup_question,
    make_task_id,
    task_tokens,
)
from governance import judge_route
from governance.schemas import RouteDecision


def route_memory(payload: MemoryRouteRequest) -> dict[str, Any]:
    message = strip_shared_memories(payload.message)
    assistant = strip_shared_memories(payload.assistant_output or "")
    hints = payload.client_hints or {}

    long_term_entries = extract_long_term_entries(message)
    if not long_term_entries and hints.get("explicit_long_term"):
        long_term_entries = extract_long_term_entries(assistant)

    heuristic_task_like = bool(hints.get("task_like")) or looks_task_worthy(message, assistant)

    def fallback_route_decision() -> RouteDecision:
        if long_term_entries and heuristic_task_like:
            return RouteDecision(
                route="mixed",
                reason="heuristic_mixed",
                confidence=0.72,
            )
        if long_term_entries:
            return RouteDecision(
                route="long_term",
                reason="heuristic_long_term",
                confidence=0.86,
            )
        if heuristic_task_like:
            return RouteDecision(
                route="task",
                reason="heuristic_task",
                confidence=0.68,
            )
        return RouteDecision(
            route="drop",
            reason="heuristic_drop",
            confidence=0.88,
        )

    route_decision = judge_route(
        message=message,
        assistant_output=assistant,
        hints=hints,
        long_term_entries=long_term_entries,
        task_like=heuristic_task_like,
        fallback=fallback_route_decision,
    )

    if route_decision.route in {"long_term", "mixed"} and not long_term_entries:
        fallback = fallback_route_decision()
        if fallback.route in {"long_term", "mixed"}:
            long_term_entries = extract_long_term_entries(message or assistant)

    task_result: Optional[dict[str, Any]] = None

    if route_decision.route in {"task", "mixed"}:
        resolution = resolve_task(
            TaskResolutionRequest(
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                project_id=payload.project_id,
                message=message,
                assistant_output=assistant,
                session_id=payload.session_id,
                channel=payload.channel,
            )
        )
        if resolution["action"] != "no_task":
            task_payload = TaskSummaryWriteRequest(
                user_id=payload.user_id,
                agent_id=payload.agent_id,
                project_id=payload.project_id,
                task_id=resolution["task_id"],
                title=resolution.get("title"),
                message=message,
                assistant_output=assistant,
            )
            structured = derive_task_summary(task_payload)
            should_materialize, task_kind, _ = evaluate_task_materialization(
                task_id=resolution["task_id"],
                title=resolution.get("title"),
                payload=task_payload,
                structured=structured,
            )
            if should_materialize:
                task_result = {
                    "task_id": resolution["task_id"],
                    "title": resolution.get("title"),
                    "summary": structured,
                    "resolution": resolution,
                    "task_kind": task_kind,
                }

    if route_decision.route == "mixed" and long_term_entries and task_result:
        return {
            "route": "mixed",
            "long_term": long_term_entries,
            "task": task_result,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    if route_decision.route == "mixed" and long_term_entries:
        return {
            "route": "long_term",
            "entries": long_term_entries,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    if route_decision.route == "long_term" and long_term_entries:
        return {
            "route": "long_term",
            "entries": long_term_entries,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    if route_decision.route == "task" and task_result:
        return {
            "route": "task",
            "task": task_result,
            "reason": route_decision.reason,
            "confidence": route_decision.confidence,
            "judge": "llm" if route_decision.from_llm else "heuristic",
        }
    return {
        "route": "drop",
        "reason": route_decision.reason,
        "confidence": route_decision.confidence,
        "judge": "llm" if route_decision.from_llm else "heuristic",
    }


def task_candidate_score(message: str, task: dict[str, Any]) -> float:
    from backend import main as _main  # noqa: PLC0415 (lazy by design)

    title = _main.normalize_text(task.get("title") or "")
    aliases = [_main.normalize_text(alias) for alias in task.get("aliases") or [] if alias]
    summary = _main.normalize_text(task.get("last_summary") or "")
    haystack = " ".join(part for part in [title, *aliases, summary] if part)
    message_normalized = _main.normalize_text(message)
    message_tokens = task_tokens(message_normalized)
    haystack_tokens = task_tokens(haystack)
    if not message_tokens or not haystack_tokens or not haystack:
        return 0.0
    overlap = len(message_tokens & haystack_tokens)
    union = len(message_tokens | haystack_tokens)
    score = overlap / union if union else 0.0

    message_lower = message_normalized.lower()
    haystack_lower = haystack.lower()
    if message_lower and message_lower in haystack_lower:
        score += 0.22
    elif title and title.lower() in message_lower:
        score += 0.18
    elif any(alias.lower() in message_lower for alias in aliases):
        score += 0.14

    if re.search(r"下一步|接下来|next step|next action", message_lower):
        if re.search(r"下一步|next action", summary.lower()):
            score += 0.14
        if re.search(r"下一步|next action", title.lower()):
            score += 0.08

    subject = extract_task_lookup_subject(message_normalized)
    if subject:
        subject_lower = subject.lower()
        if subject_lower in title.lower():
            score += 0.18
        elif any(subject_lower in alias.lower() for alias in aliases):
            score += 0.14
        elif subject_lower in summary.lower():
            score += 0.1

    return min(score, 1.0)


def resolve_task(payload: TaskResolutionRequest) -> dict[str, Any]:
    from backend import main as _main  # noqa: PLC0415 (lazy by design)

    if not looks_task_worthy(payload.message, payload.assistant_output):
        return {"action": "no_task", "task_id": None, "title": None, "confidence": 0.0, "reason": "Content is not task-like"}

    lookup_question = is_task_lookup_question(payload.message)
    tasks = [task for task in _main.fetch_tasks(payload.user_id, payload.project_id, "active") if task.get("task_kind") == "work"]
    scored = [(task_candidate_score(payload.message, task), task) for task in tasks]
    scored.sort(key=lambda item: item[0], reverse=True)

    match_threshold = 0.24 if lookup_question else 0.18
    if scored and scored[0][0] >= match_threshold:
        score, task = scored[0]
        return {
            "action": "match_existing_task",
            "task_id": task["task_id"],
            "title": task["title"],
            "confidence": round(score, 4),
            "reason": "Matched existing active task by semantic overlap",
        }

    if lookup_question:
        return {
            "action": "no_task",
            "task_id": None,
            "title": None,
            "confidence": round(scored[0][0], 4) if scored else 0.0,
            "reason": "No sufficiently relevant active task matched this lookup question",
        }

    title = derive_task_title(payload.message)
    task_id = make_task_id(title)
    structured = derive_task_summary(
        TaskSummaryWriteRequest(
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            project_id=payload.project_id,
            task_id=task_id,
            title=title,
            message=payload.message,
            assistant_output=payload.assistant_output,
        )
    )
    should_materialize, task_kind, task_reason = evaluate_task_materialization(
        task_id=task_id,
        title=title,
        payload=TaskSummaryWriteRequest(
            user_id=payload.user_id,
            agent_id=payload.agent_id,
            project_id=payload.project_id,
            task_id=task_id,
            title=title,
            message=payload.message,
            assistant_output=payload.assistant_output,
        ),
        structured=structured,
    )
    if not should_materialize:
        return {
            "action": "no_task",
            "task_id": None,
            "title": None,
            "confidence": 0.0,
            "reason": task_reason,
            "task_kind": task_kind,
        }
    return {
        "action": "propose_new_task",
        "task_id": task_id,
        "title": title,
        "confidence": 1.0,
        "reason": "Proposed a new task from task-like content",
    }


__all__ = [
    "resolve_task",
    "route_memory",
    "task_candidate_score",
]
