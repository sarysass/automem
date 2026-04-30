from __future__ import annotations

import re
from typing import Any, Optional


PROJECT_CURRENT_FACT_KEYS = {
    "project_context:current_state",
    "project_context:current_deployment_state",
    "project_context:current_next_action",
    "project_context:current_risks",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _is_project_context(metadata: Optional[dict[str, Any]]) -> bool:
    meta = metadata or {}
    return str(meta.get("category") or "") == "project_context"


def infer_project_context_fact_key(text: str, metadata: Optional[dict[str, Any]]) -> Optional[str]:
    if not _is_project_context(metadata):
        return None
    normalized = _normalize(text)
    lower = normalized.lower()
    if re.search(
        r"\b(vps|gc-jp|systemd|timer|worker|service|deploy|deployed|deployment)\b|部署|定时|治理任务|服务",
        lower,
        re.I,
    ):
        return "project_context:current_deployment_state"
    if re.search(r"\b(next action|next step|follow[- ]?up|todo|blocker)\b|下一步|接下来|阻塞", lower, re.I):
        return "project_context:current_next_action"
    if re.search(r"\b(risk|concern|problem|issue|unsafe|dissatisfied)\b|风险|问题|担心|不满意", lower, re.I):
        return "project_context:current_risks"
    if re.search(r"\b(current|currently|now|active state|state)\b|当前|目前|现在|现状", lower, re.I):
        return "project_context:current_state"
    return None


def is_archivable_project_context_process_log(text: str, metadata: Optional[dict[str, Any]]) -> bool:
    meta = metadata or {}
    if str(meta.get("domain") or "") != "long_term" or not _is_project_context(meta):
        return False
    if infer_project_context_fact_key(text, meta) in PROJECT_CURRENT_FACT_KEYS:
        return False
    normalized = _normalize(text)
    lower = normalized.lower()
    return bool(
        re.search(
            r"\bphase\s*\d+|milestone|validation|validated|review|audit|research|plan|"
            r"implemented|completed|finished|progress|handoff|rollout|refactor\b|"
            r"阶段|里程碑|验证|审查|调研|计划|已完成|完成|进展|交接|重构",
            lower,
            re.I,
        )
    )
