from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


_ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(_ENV_PATH)


@dataclass(frozen=True)
class AutomemConfig:
    memory_url: str
    memory_api_key: str
    default_user_id: str
    default_agent_id: str
    default_project_id: str | None
    search_threshold: float
    top_k: int


def load_config() -> AutomemConfig:
    memory_url = os.environ["MEMORY_URL"].rstrip("/")
    memory_api_key = os.environ["MEMORY_API_KEY"]
    default_user_id = os.environ.get("MEMORY_USER_ID", "example-user")
    default_agent_id = os.environ.get("MEMORY_AGENT_ID", "codex")
    default_project_id = os.environ.get("MEMORY_PROJECT_ID") or None
    search_threshold = float(os.environ.get("MEMORY_SEARCH_THRESHOLD", "0.35"))
    top_k = int(os.environ.get("MEMORY_TOP_K", "5"))

    return AutomemConfig(
        memory_url=memory_url,
        memory_api_key=memory_api_key,
        default_user_id=default_user_id,
        default_agent_id=default_agent_id,
        default_project_id=default_project_id,
        search_threshold=search_threshold,
        top_k=top_k,
    )
