from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


JudgeAction = Literal["drop", "store", "rewrite"]
RouteAction = Literal["drop", "long_term", "task", "mixed"]
NoiseKind = Literal[
    "empty",
    "time_scaffold",
    "cron_template",
    "transport_metadata",
    "system_prompt_scaffold",
    "heartbeat_snapshot",
    "transient_instruction",
    "assistant_chatter",
]


class TextDecision(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    action: JudgeAction = "drop"
    memory_kind: Optional[str] = None
    canonical_text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    noise_kind: Optional[NoiseKind] = None
    task_kind_override: Optional[str] = None
    store_task_memory: bool = True
    from_llm: bool = False


class RouteDecision(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    route: RouteAction = Field(default="drop", alias="action")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    memory_kind: Optional[str] = None
    from_llm: bool = False


JudgeDecision = TextDecision
