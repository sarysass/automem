#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import (
    format_recall_context,
    list_tasks,
    load_config,
    load_hook_input,
    load_last_prompt,
    pick_relevant_tasks,
    print_additional_context,
    save_last_prompt,
    search_memories,
)


def build_session_start_context() -> str:
    cfg = load_config()
    return build_session_start_context_from_hook({})


def build_session_start_context_from_hook(hook_input: dict) -> str:
    cfg = load_config()
    session_id = str(hook_input.get("session_id") or "")
    recent_prompt = load_last_prompt(cfg, session_id) if session_id else None
    tasks = pick_relevant_tasks(recent_prompt or "", list_tasks(cfg)) if recent_prompt else []
    if not cfg.memory_project_id:
        return format_recall_context([], tasks)
    memories = search_memories(cfg, f"{cfg.memory_project_id} context rules architecture", domain="long_term")
    return format_recall_context(memories, tasks)


def build_user_prompt_context(hook_input: dict) -> str:
    cfg = load_config()
    prompt = str(hook_input.get("prompt") or "").strip()
    session_id = str(hook_input.get("session_id") or "")
    if prompt and session_id:
        save_last_prompt(cfg, session_id, prompt)
    memories = search_memories(cfg, prompt, domain="long_term") if prompt else []
    tasks = pick_relevant_tasks(prompt, list_tasks(cfg)) if prompt else []
    return format_recall_context(memories, tasks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("session-start", "user-prompt"), required=True)
    args = parser.parse_args()
    hook_input = load_hook_input()
    if args.mode == "session-start":
        context = build_session_start_context_from_hook(hook_input)
        hook_event_name = "SessionStart"
    else:
        context = build_user_prompt_context(hook_input)
        hook_event_name = "UserPromptSubmit"
    print_additional_context(context, hook_event_name=hook_event_name)


if __name__ == "__main__":
    main()
