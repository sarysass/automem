"""Shared client helpers for automem CLI and adapters.

This package consolidates payload construction, HTTP client setup, response
decoding, recall formatting, and high-level capture flow. .env loading is
intentionally left to entry points (cli/memory, codex MCP server, claude-code
hooks) since each has its own resolution strategy.
"""

from automem_client.http import build_client, decode
from automem_client.operations import (
    capture_turn,
    list_active_tasks,
    memory_route_request,
    search_memories,
)
from automem_client.payloads import (
    list_tasks_params,
    memory_route_payload,
    search_payload,
    store_long_term_payload,
    store_task_summary_payload,
)
from automem_client.recall import (
    format_recall_context,
    pick_relevant_tasks,
    token_overlap_score,
)

__all__ = [
    "build_client",
    "capture_turn",
    "decode",
    "format_recall_context",
    "list_active_tasks",
    "list_tasks_params",
    "memory_route_payload",
    "memory_route_request",
    "pick_relevant_tasks",
    "search_memories",
    "search_payload",
    "store_long_term_payload",
    "store_task_summary_payload",
    "token_overlap_score",
]
