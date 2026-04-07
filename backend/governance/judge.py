from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx

from .canonicalize import canonicalize_preference_text, normalize_text
from .rules import hard_rule_decision, is_query_like_long_term_text
from .schemas import RouteDecision, TextDecision


def _infer_memory_kind(text: str) -> Optional[str]:
    lower = text.lower()
    if re.search(r"姓名|名字|我叫|我是|身份是|ceo|cto|founder|创始人|负责人", lower):
        return "user_profile"
    if re.search(r"偏好|喜欢|我希望|优先|中文|英文|summary|简洁|direct", lower):
        return "preference"
    if re.search(r"架构|方案|决定|采用|使用|decision|architecture|backend", lower):
        return "architecture_decision"
    if re.search(r"规则|约束|必须|只能|不要|must|should|never|always|tailscale|private access", lower):
        return "project_rule"
    if re.search(r"公司|团队|内部|业务|项目|产品|workflow|memory hub|codex|openclaw|automem", lower):
        return "project_context"
    return None


def _looks_task_like(message: str, assistant_output: str) -> bool:
    msg = normalize_text(message).lower()
    assistant = normalize_text(assistant_output).lower()
    if not msg and not assistant:
        return False
    if re.search(r"请记住|记住|偏好|我喜欢|我希望|名字|姓名|公司|身份|ceo|cto", msg) and not re.search(
        r"继续|实现|修复|修改|分析|排查|写|生成|搭建|部署|任务|问题|流程|继续做|next action|blocker",
        msg,
    ):
        return False
    if re.search(r"继续|实现|修复|修改|分析|排查|写|生成|搭建|部署|任务|问题|流程|继续做|共享记忆|记忆系统|routing|backend|下一步|接下来", msg):
        return True
    if re.search(r"已完成|下一步|阻塞|next step|blocker|implemented|fixed|completed|updated", assistant):
        return True
    return False


def _heuristic_memory_decision(
    *,
    text: str,
    metadata: Optional[dict[str, Any]],
    assistant_output: Optional[str],
) -> TextDecision:
    normalized = normalize_text(text)
    meta = metadata or {}
    domain = str(meta.get("domain") or "")
    category = str(meta.get("category") or "")
    route_origin = str(meta.get("route_origin") or "")
    task_kind = str(meta.get("task_kind") or "")

    hard = hard_rule_decision(normalized, meta)
    if hard:
        return hard
    if is_query_like_long_term_text(normalized) and domain != "task":
        return TextDecision(
            action="drop",
            canonical_text=normalized,
            confidence=0.97,
            reason="query_like_prompt",
            noise_kind="transient_instruction",
            store_task_memory=False,
        )
    if task_kind and task_kind != "work":
        return TextDecision(
            action="drop",
            canonical_text=normalized,
            confidence=0.98,
            reason=f"task_kind:{task_kind}",
            store_task_memory=False,
            task_kind_override=task_kind,
        )
    if domain == "task":
        if len(normalized) < 6:
            return TextDecision(
                action="drop",
                canonical_text=normalized,
                confidence=0.94,
                reason="task_text_too_short",
                noise_kind="assistant_chatter",
                store_task_memory=False,
            )
        return TextDecision(
            action="store",
            memory_kind=category or "task_summary",
            canonical_text=normalized,
            confidence=0.83,
            reason="heuristic_task_store",
            store_task_memory=True,
        )
    inferred_kind = category or _infer_memory_kind(normalized)
    if domain == "long_term":
        if not inferred_kind:
            return TextDecision(
                action="drop",
                canonical_text=normalized,
                confidence=0.82,
                reason="long_term_without_durable_signal",
                noise_kind="transient_instruction",
                store_task_memory=False,
            )
        canonical = canonicalize_preference_text(normalized) if inferred_kind == "preference" else normalized
        action = "rewrite" if canonical != normalized else "store"
        return TextDecision(
            action=action,
            memory_kind=inferred_kind,
            canonical_text=canonical,
            confidence=0.9,
            reason="heuristic_long_term_store",
            store_task_memory=False,
        )
    if route_origin == "memory_route":
        return TextDecision(
            action="store" if inferred_kind else "drop",
            memory_kind=inferred_kind or ("task_summary" if _looks_task_like(normalized, assistant_output or "") else None),
            canonical_text=normalized,
            confidence=0.62 if inferred_kind else 0.55,
            reason="heuristic_route_candidate" if inferred_kind else "route_not_durable",
            store_task_memory=bool(_looks_task_like(normalized, assistant_output or "")),
        )
    return TextDecision(
        action="drop",
        canonical_text=normalized,
        confidence=0.6,
        reason="no_durable_signal",
        store_task_memory=False,
    )


def _should_call_llm(decision: TextDecision, *, text: str, metadata: Optional[dict[str, Any]]) -> bool:
    if decision.confidence >= 0.88:
        return False
    if not text or len(text) > 1500:
        return False
    base_url = os.environ.get("ZAI_BASE_URL", "")
    api_key = os.environ.get("ZAI_API_KEY", "")
    if not base_url or not api_key or ".invalid" in base_url:
        return False
    if os.environ.get("AUTOMEM_ENABLE_LLM_GOVERNANCE", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False
    domain = str((metadata or {}).get("domain") or "")
    return domain in {"", "long_term", "task"}


def _extract_json_object(raw: str) -> Optional[dict[str, Any]]:
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


def _call_llm(messages: list[dict[str, str]]) -> Optional[dict[str, Any]]:
    api_key = os.environ.get("ZAI_API_KEY", "")
    base_url = os.environ.get("ZAI_BASE_URL", "").rstrip("/")
    model = os.environ.get("ZAI_MODEL", "glm-4.6")
    if not api_key or not base_url or ".invalid" in base_url:
        return None
    try:
        with httpx.Client(timeout=6.0, headers={"Authorization": f"Bearer {api_key}"}) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                json={
                    "model": model,
                    "temperature": 0,
                    "max_tokens": 220,
                    "response_format": {"type": "json_object"},
                    "messages": messages,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return None
    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return _extract_json_object(content if isinstance(content, str) else "")


def _llm_memory_decision(
    *,
    text: str,
    metadata: Optional[dict[str, Any]],
    assistant_output: Optional[str],
    heuristic: TextDecision,
) -> Optional[TextDecision]:
    meta = metadata or {}
    prompt = {
        "text": normalize_text(text),
        "assistant_output": normalize_text(assistant_output or ""),
        "metadata": meta,
        "heuristic": heuristic.model_dump(),
        "policy": {
            "prefer_false_negative": True,
            "drop_noise": True,
            "only_store_durable_long_term_or_real_task_progress": True,
        },
    }
    result = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a strict memory governance judge. "
                    "Return JSON only with keys: action, memory_kind, canonical_text, confidence, reason, noise_kind, store_task_memory. "
                    "Be conservative. Drop prompts, metadata, cron scaffolds, time banners, snapshots, and assistant chatter."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
    )
    if not result:
        return None
    try:
        decision = TextDecision.model_validate(result)
    except Exception:
        return None
    if not decision.canonical_text:
        decision.canonical_text = normalize_text(text)
    decision.from_llm = True
    return decision


def govern_memory_candidate(
    *,
    text: str,
    metadata: Optional[dict[str, Any]] = None,
    assistant_output: Optional[str] = None,
) -> TextDecision:
    heuristic = _heuristic_memory_decision(text=text, metadata=metadata, assistant_output=assistant_output)
    if not _should_call_llm(heuristic, text=text, metadata=metadata):
        return heuristic
    llm_decision = _llm_memory_decision(
        text=text,
        metadata=metadata,
        assistant_output=assistant_output,
        heuristic=heuristic,
    )
    return llm_decision or heuristic


def _heuristic_route_decision(
    *,
    message: str,
    assistant_output: Optional[str],
    explicit_long_term: bool,
    task_hint: bool,
) -> RouteDecision:
    normalized_message = normalize_text(message)
    normalized_assistant = normalize_text(assistant_output or "")
    if not normalized_message and not normalized_assistant:
        return RouteDecision(route="drop", confidence=0.99, reason="empty")
    message_kind = _infer_memory_kind(normalized_message) if not is_query_like_long_term_text(normalized_message) else None
    task_like = task_hint or _looks_task_like(normalized_message, normalized_assistant)
    if explicit_long_term and task_like:
        return RouteDecision(route="mixed", confidence=0.82, reason="explicit_long_term_and_task_progress", memory_kind=message_kind)
    if explicit_long_term or message_kind:
        if task_like and normalized_assistant:
            return RouteDecision(route="mixed", confidence=0.74, reason="durable_plus_task", memory_kind=message_kind)
        return RouteDecision(route="long_term", confidence=0.84 if explicit_long_term else 0.66, reason="durable_long_term_signal", memory_kind=message_kind)
    if task_like:
        return RouteDecision(route="task", confidence=0.78, reason="task_progress_signal")
    return RouteDecision(route="drop", confidence=0.7, reason="no_durable_signal")


def judge_route_candidate(
    *,
    message: str,
    assistant_output: Optional[str],
    explicit_long_term: bool,
    task_hint: bool,
    metadata: Optional[dict[str, Any]] = None,
) -> RouteDecision:
    hard = hard_rule_decision(message, metadata)
    if hard and not normalize_text(assistant_output or ""):
        return RouteDecision(route="drop", confidence=hard.confidence, reason=hard.reason, memory_kind=hard.memory_kind)
    heuristic = _heuristic_route_decision(
        message=message,
        assistant_output=assistant_output,
        explicit_long_term=explicit_long_term,
        task_hint=task_hint,
    )
    if heuristic.confidence >= 0.88 or ".invalid" in os.environ.get("ZAI_BASE_URL", ""):
        return heuristic
    result = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You classify whether a turn should become long_term memory, task memory, mixed, or drop. "
                    "Return JSON only with keys: action, confidence, reason, memory_kind. "
                    "Prefer drop over storing noisy or transient content."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": normalize_text(message),
                        "assistant_output": normalize_text(assistant_output or ""),
                        "explicit_long_term": explicit_long_term,
                        "task_hint": task_hint,
                        "metadata": metadata or {},
                        "heuristic": heuristic.model_dump(),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
    )
    if not result:
        return heuristic
    try:
        decision = RouteDecision.model_validate(result)
        decision.from_llm = True
        return decision
    except Exception:
        return heuristic


def judge_text(
    *,
    text: str,
    metadata: Optional[dict[str, Any]],
    origin: str,
    fallback,
) -> TextDecision:
    _ = origin
    heuristic = fallback()
    if not _should_call_llm(heuristic, text=text, metadata=metadata):
        return heuristic
    llm_decision = _llm_memory_decision(
        text=text,
        metadata=metadata,
        assistant_output=None,
        heuristic=heuristic,
    )
    return llm_decision or heuristic


def judge_route(
    *,
    message: str,
    assistant_output: Optional[str],
    hints: Optional[dict[str, Any]],
    long_term_entries: list[dict[str, str]],
    task_like: bool,
    fallback,
) -> RouteDecision:
    explicit_long_term = bool((hints or {}).get("explicit_long_term")) or bool(long_term_entries)
    heuristic = fallback()
    if heuristic.confidence >= 0.88 or ".invalid" in os.environ.get("ZAI_BASE_URL", ""):
        return heuristic
    route = judge_route_candidate(
        message=message,
        assistant_output=assistant_output,
        explicit_long_term=explicit_long_term,
        task_hint=task_like,
        metadata={"hints": hints or {}, "long_term_entries": long_term_entries},
    )
    return route or heuristic
