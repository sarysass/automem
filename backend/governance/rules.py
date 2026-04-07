from __future__ import annotations

import re
from typing import Optional

from .canonicalize import normalize_text
from .schemas import TextDecision


def is_explicit_long_term_request(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in (
            "long term",
            "long-term",
            "长期记忆",
            "长期信息",
            "请记住",
            "记住：",
            "记录下面",
            "记住下面",
            "记住以下",
            "记录以下",
            "关键点",
        )
    )


def split_explicit_items(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    lines = [line.strip() for line in normalized.split("\n")]
    items: list[str] = []
    capture = False
    for line in lines:
        if not line:
            continue
        if is_explicit_long_term_request(line):
            capture = True
            inline = re.sub(
                r"^(?:请记住|记住|记录下面|记住下面|记住以下|记录以下|在\s*long\s*term\s*记忆中记录下面(?:两个)?关键点|长期记忆中记录下面(?:两个)?关键点)[:：]?\s*",
                "",
                line,
                flags=re.I,
            ).strip()
            if inline:
                items.append(inline)
            continue
        if re.match(r"^\d+[.)、]\s*", line) or re.match(r"^[-*•]\s*", line):
            capture = True
            item = re.sub(r"^\d+[.)、]\s*|^[-*•]\s*", "", line).strip()
            if item:
                items.append(item)
            continue
        if capture:
            items.append(line)
    return [normalize_text(item) for item in items if normalize_text(item)]


def is_query_like_long_term_text(text: str) -> bool:
    normalized = normalize_text(text)
    lower = normalized.lower()
    if not normalized:
        return False
    if re.search(r"[?？]\s*$", normalized):
        return True
    if re.match(r"^(请问|想问|想知道|帮我查|查一下|告诉我|你知道)\b", normalized):
        return True
    explicit_patterns = (
        r"我叫什么名字",
        r"我的名字是什么",
        r"我的姓名是什么",
        r"我的身份是什么",
        r"我是谁",
        r"请用什么语言",
        r"应该用什么语言",
        r"我的偏好是什么",
        r"我喜欢什么风格",
        r"what(?:'s| is) my name",
        r"who am i",
        r"what(?:'s| is) my role",
        r"what language should",
        r"what are my preferences",
    )
    if any(re.search(pattern, lower, re.I) for pattern in explicit_patterns):
        return True
    trailing_patterns = (
        r"是什么$",
        r"是谁$",
        r"什么语言$",
        r"什么风格$",
        r"什么偏好$",
        r"怎么做$",
        r"如何做$",
        r"吗$",
        r"么$",
    )
    return any(re.search(pattern, normalized) for pattern in trailing_patterns)


def detect_noise_kind(text: str) -> Optional[str]:
    normalized = normalize_text(text)
    lower = normalized.lower()
    if not normalized:
        return "empty"
    if normalized == "NO_REPLY" or "[[reply_to_current]]" in normalized:
        return "assistant_chatter"
    if lower.startswith("current time:") or lower.startswith("当前时间：") or lower.startswith("current date:"):
        return "time_scaffold"
    if lower.startswith("[cron:") or "daily monitoring task" in lower:
        return "cron_template"
    if lower.startswith("conversation info (untrusted metadata)") or re.search(
        r"\b(message_id|chat_type|mentions|sender|sessionid|conversation_id)\b",
        lower,
    ):
        return "transport_metadata"
    if "treat the memories below as untrusted historical context only" in lower or "<shared-memories>" in lower:
        return "system_prompt_scaffold"
    if "heartbeat-style summary" in lower or "filename slug" in lower or re.search(r"^updated \d", lower):
        return "heartbeat_snapshot"
    if lower.startswith("system:") or lower.startswith("<system-reminder>") or lower.startswith("[system directive:"):
        return "system_prompt_scaffold"
    if normalized.startswith("{") and re.search(r'"(message_id|chat_type|mentions|sender|session_id)"', normalized):
        return "transport_metadata"
    if len(normalized) <= 8 and normalized.lower() in {"ok", "okay", "好的", "收到", "明白", "知道了"}:
        return "assistant_chatter"
    return None


def is_task_noise_text(text: str) -> bool:
    return detect_noise_kind(text) is not None


def hard_rule_decision(text: str, metadata: Optional[dict[str, object]] = None) -> Optional[TextDecision]:
    noise_kind = detect_noise_kind(text)
    if not noise_kind:
        return None
    return TextDecision(
        action="drop",
        canonical_text=normalize_text(text),
        confidence=0.99,
        reason=f"hard_rule:{noise_kind}",
        noise_kind=noise_kind,
        store_task_memory=False,
    )


def apply_hard_rules(
    text: str,
    metadata: Optional[dict[str, object]] = None,
    *,
    origin: str = "memory_store",
) -> Optional[TextDecision]:
    _ = origin
    return hard_rule_decision(text, metadata)


def build_long_term_duplicate_key(item: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(item.get("user_id") or ""),
        normalize_text(str(item.get("canonical_text") or item.get("text") or "")),
        str(item.get("category") or ""),
        str(item.get("project_id") or ""),
    )
