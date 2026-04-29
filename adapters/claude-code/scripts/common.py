#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from automem_client import (
    build_client,
    capture_turn as _shared_capture_turn,
    format_recall_context,
    list_active_tasks,
    pick_relevant_tasks,
    search_memories as _shared_search_memories,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _resolve_automem_root() -> Path | None:
    automem_home = os.environ.get("AUTOMEM_HOME")
    if automem_home:
        return Path(automem_home).expanduser()
    candidate = PLUGIN_ROOT.parents[2]
    if (candidate / "cli" / "memory").exists():
        return candidate
    return None


DEFAULT_REPO_ROOT = _resolve_automem_root()
DEFAULT_CLI_PATH = DEFAULT_REPO_ROOT / "cli" / "memory" if DEFAULT_REPO_ROOT else None
DEFAULT_VENV_PYTHON = DEFAULT_REPO_ROOT / ".venv" / "bin" / "python" if DEFAULT_REPO_ROOT else None


@dataclass
class RuntimeConfig:
    memory_url: str | None
    memory_api_key: str | None
    memory_user_id: str
    memory_agent_id: str
    memory_project_id: str | None
    cli_path: Path | None
    python_path: str | None
    plugin_data_dir: Path


def load_hook_input() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    return json.loads(raw) if raw else {}


def load_config() -> RuntimeConfig:
    cli_env = os.environ.get("AUTOMEM_CLI")
    cli_path = Path(cli_env).expanduser() if cli_env else None
    if cli_path and not cli_path.exists():
        cli_path = None
    if cli_path is None and DEFAULT_CLI_PATH and DEFAULT_CLI_PATH.exists():
        cli_path = DEFAULT_CLI_PATH

    python_env = os.environ.get("AUTOMEM_PYTHON")
    python_path = python_env or (str(DEFAULT_VENV_PYTHON) if DEFAULT_VENV_PYTHON and DEFAULT_VENV_PYTHON.exists() else None)

    plugin_data = Path(os.environ.get("CLAUDE_PLUGIN_DATA", str(PLUGIN_ROOT / ".plugin-data")))
    plugin_data.mkdir(parents=True, exist_ok=True)

    return RuntimeConfig(
        memory_url=os.environ.get("MEMORY_URL"),
        memory_api_key=os.environ.get("MEMORY_API_KEY"),
        memory_user_id=os.environ.get("MEMORY_USER_ID", "example-user"),
        memory_agent_id=os.environ.get("MEMORY_AGENT_ID", "claude-code"),
        memory_project_id=os.environ.get("MEMORY_PROJECT_ID") or None,
        cli_path=cli_path,
        python_path=python_path,
        plugin_data_dir=plugin_data,
    )


def _run_cli(cfg: RuntimeConfig, args: list[str]) -> dict[str, Any]:
    if not cfg.cli_path:
        raise RuntimeError("automem CLI is not configured")
    if cfg.python_path:
        command = [cfg.python_path, str(cfg.cli_path), *args]
    else:
        command = [str(cfg.cli_path), *args]
    env = os.environ.copy()
    completed = subprocess.run(command, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "CLI command failed")
    output = completed.stdout.strip()
    return json.loads(output) if output else {}


def _http_client(cfg: RuntimeConfig):
    if not cfg.memory_url or not cfg.memory_api_key:
        raise RuntimeError("MEMORY_URL or MEMORY_API_KEY is missing")
    return build_client(url=cfg.memory_url.rstrip("/"), key=cfg.memory_api_key, timeout=30.0)


def search_memories(cfg: RuntimeConfig, query: str, *, domain: str | None = "long_term") -> list[dict[str, Any]]:
    if cfg.cli_path:
        args = ["search", "--query", query, "--user-id", cfg.memory_user_id]
        if cfg.memory_agent_id:
            args.extend(["--agent-id", cfg.memory_agent_id])
        if cfg.memory_project_id:
            args.extend(["--project-id", cfg.memory_project_id])
        if domain:
            args.extend(["--domain", domain])
        result = _run_cli(cfg, args)
        return result.get("results", [])
    filters: dict[str, Any] = {}
    if domain:
        filters["domain"] = domain
    if cfg.memory_project_id:
        filters["project_id"] = cfg.memory_project_id
    with _http_client(cfg) as client:
        return _shared_search_memories(
            client,
            query=query,
            user_id=cfg.memory_user_id,
            agent_id=cfg.memory_agent_id,
            filters=filters or None,
        )


def list_tasks(cfg: RuntimeConfig) -> list[dict[str, Any]]:
    if cfg.cli_path:
        args = ["task", "list", "--user-id", cfg.memory_user_id]
        if cfg.memory_project_id:
            args.extend(["--project-id", cfg.memory_project_id])
        result = _run_cli(cfg, args)
        return result.get("tasks", [])
    with _http_client(cfg) as client:
        return list_active_tasks(
            client,
            user_id=cfg.memory_user_id,
            project_id=cfg.memory_project_id,
        )


def capture_turn(
    cfg: RuntimeConfig,
    *,
    message: str,
    assistant_output: str,
    explicit_long_term: bool,
    task_like: bool,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    if should_skip_capture(message, assistant_output):
        return {"status": "skipped", "reason": "noise"}
    scope_key = capture_scope_key(session_id)
    fingerprint = build_capture_fingerprint(message, assistant_output)
    if is_duplicate_capture(cfg, scope_key=scope_key, fingerprint=fingerprint):
        return {"status": "skipped", "reason": "duplicate"}

    if cfg.cli_path:
        args = [
            "capture",
            "--user-id",
            cfg.memory_user_id,
            "--agent-id",
            cfg.memory_agent_id,
            "--message",
            message,
            "--assistant-output",
            assistant_output,
            "--source",
            "claude-code",
        ]
        if cfg.memory_project_id:
            args.extend(["--project-id", cfg.memory_project_id])
        if session_id:
            args.extend(["--session-id", session_id])
        if channel:
            args.extend(["--channel", channel])
        if explicit_long_term:
            args.append("--explicit-long-term")
        if task_like:
            args.append("--task-like")
        result = _run_cli(cfg, args)
        mark_capture_success(cfg, scope_key=scope_key, fingerprint=fingerprint)
        return result

    with _http_client(cfg) as client:
        result = _shared_capture_turn(
            client,
            user_id=cfg.memory_user_id,
            message=message,
            assistant_output=assistant_output,
            agent_id=cfg.memory_agent_id,
            project_id=cfg.memory_project_id,
            session_id=session_id,
            channel=channel,
            client_hints={
                "explicit_long_term": explicit_long_term,
                "task_like": task_like,
                "source": "claude-code",
            },
        )
    mark_capture_success(cfg, scope_key=scope_key, fingerprint=fingerprint)
    return result


def session_state_path(cfg: RuntimeConfig, session_id: str) -> Path:
    state_dir = cfg.plugin_data_dir / "session-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{session_id}.json"


def save_last_prompt(cfg: RuntimeConfig, session_id: str, prompt: str) -> None:
    session_state_path(cfg, session_id).write_text(json.dumps({"last_prompt": prompt}, ensure_ascii=False))


def load_last_prompt(cfg: RuntimeConfig, session_id: str) -> str | None:
    path = session_state_path(cfg, session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text()).get("last_prompt")
    except json.JSONDecodeError:
        return None


def looks_explicit_long_term(text: str) -> bool:
    lower = text.lower()
    return any(token in lower for token in ("请记住", "记住", "long term", "long-term", "长期记忆"))


def looks_task_like(user_text: str, assistant_text: str) -> bool:
    user = normalize_text(user_text).lower()
    assistant = normalize_text(assistant_text).lower()
    if not user and not assistant:
        return False
    if looks_explicit_long_term(user):
        return False
    if is_system_noise_text(user) or is_system_noise_text(assistant):
        return False
    if re.search(r"下一步|阻塞|待办|里程碑|\b(next step|next action|blocker|blocked|todo|milestone)\b", assistant):
        return True
    work_intent = re.search(
        r"继续|实现|修复|分析|排查|部署|测试|重构|优化|\b(fix|implement|debug|deploy|refactor|optimi[sz]e|test)\b",
        user,
    )
    progress_signal = re.search(r"已完成|完成了|已修复|已更新|\b(completed|implemented|fixed|updated|shipped)\b", assistant)
    return bool(work_intent and progress_signal)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_system_noise_text(text: str) -> bool:
    normalized = normalize_text(text).lower()
    if not normalized:
        return True
    return (
        normalized.startswith("[cron:")
        or normalized.startswith("conversation info (untrusted metadata)")
        or normalized.startswith("system:")
        or normalized == "no_reply"
        or "[[reply_to_current]]" in normalized
    )


def should_skip_capture(message: str, assistant_output: str) -> bool:
    user = normalize_text(message)
    assistant = normalize_text(assistant_output)
    if not user or not assistant:
        return True
    if len(user) < 4 or len(assistant) < 4:
        return True
    if is_system_noise_text(user) or is_system_noise_text(assistant):
        return True
    return False


def capture_state_path(cfg: RuntimeConfig) -> Path:
    return cfg.plugin_data_dir / "capture-state.json"


def load_capture_state(cfg: RuntimeConfig) -> dict[str, Any]:
    path = capture_state_path(cfg)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_capture_state(cfg: RuntimeConfig, state: dict[str, Any]) -> None:
    capture_state_path(cfg).write_text(json.dumps(state, ensure_ascii=False))


def capture_scope_key(session_id: str | None) -> str:
    return normalize_text(session_id or "") or "__global__"


def build_capture_fingerprint(message: str, assistant_output: str) -> str:
    fingerprint_source = f"{normalize_text(message)}\n---\n{normalize_text(assistant_output)}"
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()


def is_duplicate_capture(cfg: RuntimeConfig, *, scope_key: str, fingerprint: str) -> bool:
    state = load_capture_state(cfg)
    last_by_scope = state.get("last_fingerprint_by_scope")
    if isinstance(last_by_scope, dict) and last_by_scope.get(scope_key) == fingerprint:
        return True
    if scope_key == "__global__" and state.get("last_fingerprint") == fingerprint:
        return True
    return False


def mark_capture_success(cfg: RuntimeConfig, *, scope_key: str, fingerprint: str) -> None:
    state = load_capture_state(cfg)
    last_by_scope = state.get("last_fingerprint_by_scope")
    if not isinstance(last_by_scope, dict):
        last_by_scope = {}
    last_by_scope[scope_key] = fingerprint
    state["last_fingerprint_by_scope"] = last_by_scope
    state["last_fingerprint"] = fingerprint
    save_capture_state(cfg, state)


def print_additional_context(text: str, *, hook_event_name: str) -> None:
    if not text:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": hook_event_name,
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )
    )


# Re-exported from automem_client for backward compatibility with hooks scripts.
__all__ = [
    "RuntimeConfig",
    "build_capture_fingerprint",
    "capture_scope_key",
    "capture_turn",
    "format_recall_context",
    "is_duplicate_capture",
    "is_system_noise_text",
    "list_tasks",
    "load_capture_state",
    "load_config",
    "load_hook_input",
    "load_last_prompt",
    "looks_explicit_long_term",
    "looks_task_like",
    "mark_capture_success",
    "normalize_text",
    "pick_relevant_tasks",
    "print_additional_context",
    "save_capture_state",
    "save_last_prompt",
    "search_memories",
    "should_skip_capture",
]
