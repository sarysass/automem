from __future__ import annotations

import re
from typing import Optional

from .canonicalize import normalize_text


def _looks_conversational_title(title: str) -> bool:
    normalized = normalize_text(title)
    lowered = normalized.lower()
    if not normalized:
        return False
    if re.search(r"(吗|嘛|呢|啥|什么|哪些|怎么|如何|是不是|对吧|可以吗|行吗|能吗|是什么意思)[？?]?$", normalized, re.I):
        return True
    if lowered.startswith("[search-mode]") or lowered.startswith("[analyze-mode]"):
        return True
    if lowered.startswith("<system-reminder>") or lowered.startswith("[system directive:"):
        return True
    if lowered.startswith("[media attached:") or "media/inbound/" in lowered:
        return True
    if any(
        lowered.startswith(prefix)
        for prefix in (
            "你",
            "我",
            "当前",
            "现在",
            "所以",
            "先",
            "行，",
            "ok",
            "okay",
        )
    ) and not re.search(
        r"安装|实现|修复|排查|分析|部署|清理|重构|优化|验证|归档|迁移|升级|处理|编写|设计|install|fix|debug|deploy|cleanup|refactor|optimi[sz]e|verify|migrate|upgrade",
        lowered,
        re.I,
    ):
        return True
    return False


def classify_task_kind(
    *,
    task_id: Optional[str],
    title: Optional[str],
    last_summary: Optional[str],
    source_agent: Optional[str],
    project_id: Optional[str],
) -> str:
    haystack = " ".join(part for part in [task_id or "", title or "", last_summary or "", source_agent or ""] if part)
    lowered = normalize_text(haystack).lower()
    if not lowered:
        return "work"
    if task_id and str(task_id).startswith("task_cron-"):
        return "system"
    if _looks_conversational_title(title or ""):
        return "meta"
    if any(
        token in lowered
        for token in (
            "watchdog",
            "monitor lowendtalk",
            "cron:",
            "conversation info (untrusted metadata)",
            "system:",
            "current time:",
            "当前时间：",
            "message_id",
            "feishu[ping]",
            "feishu[bing]",
            "background task completed",
            "all background tasks complete",
            "system reminder",
        )
    ):
        return "system"
    if any(
        token in lowered
        for token in (
            "没有成型的 task / todo 清单",
            "没有成型的 task/todo 清单",
            "没有挂着的执行任务",
            "what's next",
            "what is next",
        )
    ):
        return "meta"
    if project_id:
        return "work"
    if any(
        token in lowered
        for token in (
            "heartbeat-style summary",
            "filename slug",
            "updated ",
            "daily monitoring task",
            "snapshot",
        )
    ):
        return "snapshot"
    normalized_title = normalize_text(title or "")
    if normalized_title and re.search(
        r"(下一步是什么|接下来是什么|任务状态是什么|执行任务状态是什么|what('?s| is) next)[？?]?$",
        normalized_title,
        re.I,
    ):
        return "meta"
    if source_agent and str(source_agent).startswith("openclaw-") and ("reply_to_current" in lowered or "共享 memory" in lowered):
        return "meta"
    return "work"


def should_store_task_memory(task_kind: Optional[str]) -> bool:
    return (task_kind or "work") == "work"


def should_materialize_task(
    *,
    task_kind: Optional[str],
    title: Optional[str],
    last_summary: Optional[str],
) -> bool:
    if not should_store_task_memory(task_kind):
        return False
    normalized_title = normalize_text(title or "")
    normalized_summary = normalize_text(last_summary or "")
    if not normalized_title and not normalized_summary:
        return False
    if _looks_conversational_title(normalized_title):
        return False
    return True


def filter_task_memory_fields(
    *,
    task_kind: Optional[str],
    fields: dict[str, Optional[str]],
    judge_field,
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    decisions: dict[str, dict[str, object]] = {}
    approved: dict[str, str] = {}
    if not should_store_task_memory(task_kind):
        for field, value in fields.items():
            if not value:
                continue
            decisions[field] = {
                "action": "drop",
                "reason": f"task_kind:{task_kind}",
                "store_task_memory": False,
            }
        return approved, decisions
    for field, value in fields.items():
        if not value:
            continue
        decision = judge_field(field, value)
        payload = decision.model_dump() if hasattr(decision, "model_dump") else dict(decision)
        decisions[field] = payload
        if payload.get("action") == "drop" or not payload.get("store_task_memory", True):
            continue
        canonical = str(payload.get("canonical_text") or value).strip()
        if canonical:
            approved[field] = canonical
    return approved, decisions
