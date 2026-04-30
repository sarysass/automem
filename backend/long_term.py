"""Long-term memory extraction + governance helpers.

This is the layer between raw incoming text (a chat turn, a hook
capture) and the governance verdict (store / rewrite / drop). It owns:

- Stripping the agent's own <shared-memories> echoes back out of
  incoming text so they cannot loop into long-term again.
- Detecting "please remember X" intent (explicit long-term request).
- Splitting bullet/list items, inferring categories, and producing
  canonical entries via canonicalize_explicit_long_term_item.
- The fallback governance decision (`fallback_text_decision`) used
  when the LLM judge is offline or rejects the call.
- The final glue: `govern_memory_text(text, metadata)` that
  applies hard_rules first, then the LLM judge, then falls back.
- The cross-cutting heuristic `looks_task_worthy` used by route_memory.

Pure functions. No SQLite, no mem0. Imports backend.governance.* and
backend.schemas/tasks for shared primitives.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.governance import (
    apply_hard_rules,
    canonicalize_preference_text as governance_canonicalize_preference_text,
    is_query_like_long_term_text as governance_is_query_like_long_term_text,
    judge_text,
)
from backend.governance.schemas import TextDecision
from backend.schemas import Message
from backend.tasks import split_sentences


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def strip_shared_memories(text: str) -> str:
    return _normalize_text(re.sub(r"<shared-memories>.*?</shared-memories>", " ", text, flags=re.S))


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
    return [_normalize_text(item) for item in items if _normalize_text(item)]


def infer_long_term_category(text: str) -> Optional[str]:
    lower = text.lower()
    if re.search(r"姓名|名字|我叫", lower):
        return "user_profile"
    if re.search(r"偏好|喜欢|我希望|优先|中文|英文|summary|简洁|direct", lower):
        return "preference"
    if re.search(r"架构|方案|决定|采用|使用|decision|architecture|backend", lower):
        return "architecture_decision"
    if re.search(r"规则|约束|必须|只能|不要|must|should|never|always|tailscale|private access", lower):
        return "project_rule"
    if re.search(r"公司|团队|内部|业务|项目|产品|workflow|memory hub|codex|openclaw", lower):
        return "project_context"
    if re.search(r"我是|身份是|ceo|cto|founder|创始人|负责人", lower):
        return "user_profile"
    return None


def is_query_like_long_term_text(text: str) -> bool:
    return governance_is_query_like_long_term_text(text)


def canonicalize_explicit_long_term_item(item: str) -> list[dict[str, str]]:
    text = _normalize_text(re.sub(r"^(请记住|记住)[:：]?\s*", "", item))
    if is_query_like_long_term_text(text):
        return []
    out: list[dict[str, str]] = []

    def add(text_value: str, category: str) -> None:
        normalized = _normalize_text(text_value)
        if normalized and not any(x["text"] == normalized and x["category"] == category for x in out):
            out.append({"text": normalized, "category": category})

    name_match = re.search(r"(?:我的名字叫|我叫|姓名是|名字是)\s*([^\s，,。；;]+)", text)
    if name_match:
        add(f"姓名是{name_match.group(1)}", "user_profile")

    company_match = re.search(r"(?:我的公司(?:叫|是)?|公司(?:叫|是))\s*([^\s，,。；;]+)", text)
    if company_match:
        add(f"公司是{company_match.group(1)}", "project_context")
    reverse_company_match = re.search(r"([^\s，,。；;]+)\s*是我的公司", text)
    if reverse_company_match:
        add(f"公司是{reverse_company_match.group(1)}", "project_context")

    role_match = re.search(
        r"(?:我是|身份是)\s*([A-Za-z][A-Za-z0-9_-]*|CEO|CTO|COO|CFO|Founder|创始人|负责人)",
        text,
        re.IGNORECASE,
    )
    if roleMatch := role_match:
        add(f"身份是{roleMatch.group(1).rstrip('。')}", "user_profile")

    if not out:
        inferred = infer_long_term_category(text)
        if inferred:
            add(text, inferred)

    return out


def extract_long_term_entries(text: str) -> list[dict[str, str]]:
    raw_text = strip_shared_memories(text)
    normalized = _normalize_text(raw_text)
    if not normalized:
        return []

    entries: list[dict[str, str]] = []
    if is_explicit_long_term_request(raw_text):
        for item in split_explicit_items(raw_text):
            entries.extend(canonicalize_explicit_long_term_item(item))
    else:
        candidates = split_sentences(normalized) or [normalized]
        for candidate in candidates:
            if is_query_like_long_term_text(candidate):
                continue
            inferred = infer_long_term_category(candidate)
            if inferred:
                entries.append({"text": candidate, "category": inferred})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["text"], entry["category"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def extract_primary_message_text(messages: list[Message]) -> str:
    user_parts = [
        _normalize_text(message.content)
        for message in messages
        if message.role == "user" and _normalize_text(message.content)
    ]
    if user_parts:
        return "\n".join(user_parts)
    fallback_parts = [_normalize_text(message.content) for message in messages if _normalize_text(message.content)]
    return "\n".join(fallback_parts)


def is_preference_noise_text(text: str) -> bool:
    normalized = _normalize_text(text)
    lower = normalized.lower()
    if len(normalized) > 220:
        return True
    patterns = (
        r"based on this conversation",
        r"treat the memories below as untrusted historical context only",
        r"<shared-memories>",
        r"\[cron:",
        r"daily monitoring task",
        r"heartbeat-style summary",
        r"filename slug",
    )
    return any(re.search(pattern, lower, re.I) for pattern in patterns)


def canonicalize_preference_text(text: str) -> str:
    return governance_canonicalize_preference_text(text)


def is_task_noise_text(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True
    if normalized == "NO_REPLY":
        return True
    return "[[reply_to_current]]" in normalized


def fallback_text_decision(text: str, metadata: Optional[dict[str, Any]]) -> TextDecision:
    normalized = _normalize_text(text)
    meta = metadata or {}
    domain = str(meta.get("domain") or "")
    category = str(meta.get("category") or "")

    if not normalized:
        return TextDecision(action="drop", canonical_text="", reason="fallback_empty", confidence=1.0)
    if domain == "task" and is_task_noise_text(normalized):
        return TextDecision(
            action="drop",
            canonical_text="",
            reason="fallback_task_noise",
            confidence=0.98,
            noise_kind="assistant_chatter",
            store_task_memory=False,
        )
    if domain == "long_term" and category == "preference":
        if is_preference_noise_text(normalized):
            return TextDecision(
                action="drop",
                canonical_text="",
                reason="fallback_preference_noise",
                confidence=0.95,
                noise_kind="transient_instruction",
            )
        canonical = canonicalize_preference_text(normalized)
        return TextDecision(
            action="rewrite" if canonical != normalized else "store",
            canonical_text=canonical,
            reason="fallback_preference_canonicalized" if canonical != normalized else "fallback_preference_accept",
            confidence=0.9,
            memory_kind="preference",
        )
    return TextDecision(
        action="store",
        canonical_text=normalized,
        reason="fallback_accept",
        confidence=0.6,
        memory_kind=category or infer_long_term_category(normalized),
    )


def govern_text_decision(text: str, metadata: Optional[dict[str, Any]], *, origin: str = "memory_store") -> TextDecision:
    normalized = _normalize_text(text)
    hard_rule = apply_hard_rules(normalized, metadata, origin=origin)
    if hard_rule is not None:
        return hard_rule
    return judge_text(
        text=normalized,
        metadata=metadata,
        origin=origin,
        fallback=lambda: fallback_text_decision(normalized, metadata),
    )


def govern_memory_text(text: str, metadata: Optional[dict[str, Any]], *, origin: str = "memory_store") -> dict[str, Any]:
    decision = govern_text_decision(text, metadata, origin=origin)
    return {
        "action": "skip" if decision.action == "drop" else "store",
        "reason": "noise" if decision.action == "drop" and decision.noise_kind else decision.reason,
        "text": decision.canonical_text,
        "canonicalized": decision.action == "rewrite",
        "noise_kind": decision.noise_kind,
        "confidence": decision.confidence,
        "from_llm": decision.from_llm,
        "store_task_memory": decision.store_task_memory,
        "memory_kind": decision.memory_kind,
    }


def looks_task_worthy(message: str, assistant_output: Optional[str]) -> bool:
    msg = strip_shared_memories(message).lower()
    assistant = strip_shared_memories(assistant_output or "").lower()

    if not msg and not assistant:
        return False
    if is_explicit_long_term_request(msg):
        return False
    if re.search(r"没有成型的 task / todo 清单|没有成型的 task/todo 清单|没有挂着的执行任务", assistant):
        return False
    if re.search(r"(当前|现在).*(执行任务|任务状态).*(什么|如何|？|\?)", msg):
        return False
    if re.search(r"请记住|记住|偏好|我喜欢|我希望|名字|姓名|公司|身份|ceo|cto", msg) and not re.search(
        r"继续|实现|修复|分析|排查|写|生成|搭建|部署|任务|流程|继续做|next action|blocker", msg
    ):
        return False
    if re.search(r"继续|实现|修复|修改|分析|排查|写|生成|搭建|部署|任务|问题|流程|继续做|shared memory|记忆系统|routing|backend|下一步|接下来", msg):
        return True
    if re.search(r"已完成|下一步|阻塞|next step|blocker|implemented|fixed|completed|updated", assistant):
        return True
    return False


__all__ = [
    "canonicalize_explicit_long_term_item",
    "canonicalize_preference_text",
    "extract_long_term_entries",
    "extract_primary_message_text",
    "fallback_text_decision",
    "govern_memory_text",
    "govern_text_decision",
    "infer_long_term_category",
    "is_explicit_long_term_request",
    "is_preference_noise_text",
    "is_query_like_long_term_text",
    "is_task_noise_text",
    "looks_task_worthy",
    "split_explicit_items",
    "strip_shared_memories",
]
