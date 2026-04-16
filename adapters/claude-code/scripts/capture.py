#!/usr/bin/env python3
from __future__ import annotations

import json

from common import (
    capture_turn,
    load_config,
    load_hook_input,
    load_last_prompt,
)


def main() -> None:
    cfg = load_config()
    hook_input = load_hook_input()
    if hook_input.get("stop_hook_active"):
        return

    session_id = str(hook_input.get("session_id") or "")
    assistant_output = str(hook_input.get("last_assistant_message") or "").strip()
    if not session_id or not assistant_output:
        return

    user_prompt = load_last_prompt(cfg, session_id) or ""
    if not user_prompt:
        return

    result = capture_turn(
        cfg,
        message=user_prompt,
        assistant_output=assistant_output,
        explicit_long_term=False,
        task_like=False,
        session_id=session_id,
        channel="claude-code/Stop",
    )

    log_dir = cfg.plugin_data_dir / "capture-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{session_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
