"""Task-domain helpers: title sanitization, summary derivation, lookup parsing,
materialization gate.

Pure functions plus a thin delegation to backend.governance for classify
+ should_materialize. No SQLite here — the tasks table still lives in
backend.main (route handlers and full-task list logic are tightly bound
to other in-flight code that hasn't been split yet).

backend.main re-exports every public name so adapters and tests using
`from backend.main import sanitize_task_title` keep working unchanged.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.schemas import TaskSummaryWriteRequest
from backend.governance import (
    classify_task_kind as governance_classify_task_kind,
    should_materialize_task as governance_should_materialize_task,
)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def split_sentences(text: str) -> list[str]:
    return [_normalize_text(part) for part in re.split(r"[\n。！？!?;；]+", text) if _normalize_text(part)]


def compact_text(text: Optional[str], limit: int = 240) -> Optional[str]:
    if not text:
        return None
    normalized = _normalize_text(text)
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def derive_task_title(message: str) -> str:
    msg = _normalize_text(message)
    candidates = split_sentences(message)
    if not candidates:
        return msg[:80] or "untitled-task"
    first = candidates[0]
    return first[:80]


def strip_markdown_noise(text: str) -> str:
    cleaned = re.sub(r"\[\[reply_to_current\]\]\s*", "", text)
    cleaned = re.sub(r"```(?:json)?", " ", cleaned)
    cleaned = cleaned.replace("```", " ")
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r"#+\s*", "", cleaned)
    cleaned = cleaned.replace("`", "")
    return _normalize_text(cleaned)


def summarize_title_candidate(text: str, limit: int = 56) -> str:
    cleaned = strip_markdown_noise(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(查清了，)?结论先说[:：]?\s*", "", cleaned)
    cleaned = re.sub(r"^已完成[^，。]*[，,:：]\s*下一步(?:是|为)?\s*", "", cleaned)
    cleaned = re.sub(r"^如果用户需要[，,:：]\s*", "", cleaned)
    parts = split_sentences(cleaned)
    candidate = parts[0] if parts else cleaned
    return compact_text(candidate, limit) or ""


def sanitize_task_summary_preview(text: Optional[str], limit: int = 160) -> Optional[str]:
    cleaned = strip_markdown_noise(text or "")
    if not cleaned or cleaned == "NO_REPLY":
        return None
    lowered = cleaned.lower()
    if (
        ("task todo pending deadline follow-up next action" in lowered)
        or (
            "待办" in cleaned
            and "跟进" in cleaned
            and ("截止" in cleaned or "deadline" in lowered)
        )
    ):
        return "梳理待办、跟进与截止项"
    cleaned = re.sub(r"^已完成[^，。]*[，,:：]\s*下一步(?:是|为)?\s*", "", cleaned)
    cleaned = re.sub(r"^目前我这次查到的[^，。]*[，,:：]\s*", "", cleaned)
    cleaned = re.sub(r"^现在我手上[^，。]*[，,:：]\s*", "", cleaned)
    parts = split_sentences(cleaned)
    candidate = parts[0] if parts else cleaned
    candidate = candidate.strip(" -—–")
    if not candidate or candidate == "NO_REPLY":
        return None
    return compact_text(candidate, limit)


def rewrite_task_title_from_content(text: str) -> str:
    cleaned = strip_markdown_noise(text)
    lowered = cleaned.lower()
    if not cleaned:
        return ""
    if "没有成型的 task / todo 清单" in cleaned or "没有成型的 task/todo 清单" in cleaned:
        return "共享记忆任务清单核查"
    if "没有挂着的执行任务" in cleaned or "进行中的任务：没有" in cleaned:
        return "当前执行任务状态核查"
    if "opencode orphan watchdog" in lowered or "watchdog" in lowered:
        return "Mac OpenCode 孤儿进程巡检"
    if "monitor lowendtalk 214004" in lowered:
        return "LowEndTalk 214004 库存巡检"
    if "已完成的实际测试" in cleaned and ("压缩" in cleaned or "video-compress" in lowered or "simpleencoder" in lowered):
        return "视频压缩方案实测总结"
    if "共享记忆系统" in cleaned and "task resolution" in lowered and "全端" in cleaned:
        return "共享记忆系统 task resolution 中心化与全端验证"
    if "共享记忆系统" in cleaned and "task resolution" in lowered and "中心化改造" in cleaned:
        return "共享记忆系统 task resolution 中心化改造"
    if "frontend font and overflow fix completed and verified" in lowered or "frontend typography" in lowered:
        return "前端字体与溢出修复验证"
    return ""


def humanize_task_id(task_id: str) -> str:
    text = re.sub(r"^task_", "", task_id)
    text = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", " ", text, flags=re.I)
    text = re.sub(r"[-_]+", " ", text)
    text = _normalize_text(text)
    return compact_text(text, 56) or "untitled-task"


def rewrite_keyword_soup_title(text: str) -> str:
    lowered = _normalize_text(text).lower()
    if (
        ("todo" in lowered or "待办" in lowered)
        and ("follow-up" in lowered or "follow up" in lowered or "跟进" in lowered)
        and ("deadline" in lowered or "截止" in lowered)
    ):
        return "待办任务跟进与截止项"
    return ""


def sanitize_task_title(title: Optional[str], *, last_summary: Optional[str], task_id: Optional[str]) -> str:
    raw = _normalize_text(title or "")
    if raw:
        rewritten = rewrite_keyword_soup_title(raw)
        if rewritten:
            return rewritten
        content_rewrite = rewrite_task_title_from_content(raw)
        if content_rewrite:
            return content_rewrite
        cron_match = re.match(r"^\[cron:[0-9a-f-]+\s+(.*?)(?:\]\s*.*)?$", raw, re.I)
        if cron_match:
            candidate = summarize_title_candidate(cron_match.group(1))
            if candidate:
                return candidate
        looks_bad = (
            raw == "NO_REPLY"
            or raw.lower().startswith("conversation info (untrusted metadata)")
            or raw.lower().startswith("system:")
            or raw.lower().startswith("[cron:")
            or raw.lower().startswith("updated ")
            or "message_id" in raw
            or raw.startswith("{")
        )
        if not looks_bad:
            candidate = summarize_title_candidate(raw, limit=80)
            if candidate:
                return candidate

    summary_candidate = summarize_title_candidate(last_summary or "")
    content_rewrite = rewrite_task_title_from_content(last_summary or "")
    if content_rewrite:
        return content_rewrite
    if summary_candidate and summary_candidate != "NO_REPLY":
        return summary_candidate
    if task_id:
        return humanize_task_id(task_id)
    return "untitled-task"


def task_display_title(task: dict[str, Any]) -> str:
    return sanitize_task_title(
        task.get("title"),
        last_summary=task.get("last_summary"),
        task_id=task.get("task_id"),
    )


def classify_task_kind(
    *,
    task_id: Optional[str],
    title: Optional[str],
    last_summary: Optional[str],
    source_agent: Optional[str],
    project_id: Optional[str],
) -> str:
    return governance_classify_task_kind(
        task_id=task_id,
        title=title,
        last_summary=last_summary,
        source_agent=source_agent,
        project_id=project_id,
    )


def make_task_id(title: str) -> str:
    normalized = _normalize_text(title).lower()
    slug = re.sub(r"[^a-z0-9一-鿿]+", "-", normalized).strip("-")
    slug = slug[:48] or "task"
    return f"task_{slug}"


def task_tokens(text: str) -> set[str]:
    normalized = _normalize_text(text).lower()
    stopwords = {
        "我们",
        "现在",
        "这个",
        "那个",
        "然后",
        "进行",
        "继续",
        "一下",
        "一下子",
        "task",
        "project",
        "system",
    }
    segments = re.findall(r"[a-z0-9]+|[一-鿿]+", normalized)
    tokens: set[str] = set()
    for segment in segments:
        if not segment or segment in stopwords:
            continue
        if re.fullmatch(r"[a-z0-9]+", segment):
            if len(segment) >= 2:
                tokens.add(segment)
            continue
        if len(segment) >= 2:
            tokens.add(segment)
        max_n = min(4, len(segment))
        for n in range(2, max_n + 1):
            for index in range(0, len(segment) - n + 1):
                gram = segment[index : index + n]
                if gram and gram not in stopwords:
                    tokens.add(gram)
    return tokens


def is_task_lookup_question(message: str) -> bool:
    normalized = _normalize_text(message).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"(下一步|接下来|任务状态|进展|阻塞|handoff|blocker|next step|next action).*(什么|如何|吗|？|\?)",
            normalized,
            re.I,
        )
        or re.search(
            r"(什么|如何|吗|？|\?).*(下一步|接下来|任务状态|进展|阻塞|handoff|blocker|next step|next action)",
            normalized,
            re.I,
        )
    )


def extract_task_lookup_subject(message: str) -> str:
    normalized = _normalize_text(message)
    if not normalized:
        return ""
    patterns = [
        r"(.+?)的下一步是什么",
        r"(.+?)接下来是什么",
        r"(.+?)的任务状态是什么",
        r"(.+?)的进展是什么",
        r"(.+?)的阻塞是什么",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        subject = _normalize_text(match.group(1))
        subject = re.sub(r"^(请问|帮我看下|帮我看看|看看|告诉我)\s*", "", subject)
        if subject:
            return subject
    return ""


def task_subject_matches(text: str, subject: str) -> bool:
    normalized_text = _normalize_text(text).lower()
    normalized_subject = _normalize_text(subject).lower()
    if not normalized_text or not normalized_subject:
        return False
    if normalized_subject in normalized_text:
        return True
    subject_tokens = task_tokens(normalized_subject)
    if not subject_tokens:
        return False
    text_tokens = task_tokens(normalized_text)
    overlap = subject_tokens & text_tokens
    return len(overlap) >= max(1, min(2, len(subject_tokens)))


def derive_task_summary(payload: TaskSummaryWriteRequest) -> dict[str, Optional[str]]:
    message = _normalize_text(payload.message or "")
    assistant = _normalize_text(payload.assistant_output or "")
    summary = compact_text(payload.summary)
    progress = compact_text(payload.progress)
    blocker = compact_text(payload.blocker)
    next_action = compact_text(payload.next_action)

    if not summary:
        if assistant:
            summary = compact_text(assistant, 180)
        elif message:
            summary = compact_text(message, 180)

    if not progress and assistant and re.search(r"已完成|完成了|implemented|fixed|updated|created|done|completed", assistant, re.I):
        progress = compact_text(assistant, 220)
    if not blocker and assistant and re.search(r"阻塞|blocker|blocked", assistant, re.I):
        blocker = compact_text(assistant, 160)
    if not next_action and assistant and re.search(r"下一步|接下来|next step|next action", assistant, re.I):
        next_action = compact_text(assistant, 160)

    return {
        "summary": summary,
        "progress": progress,
        "blocker": blocker,
        "next_action": next_action,
    }


def task_has_actionable_signal(
    *,
    title: Optional[str],
    message: Optional[str],
    assistant_output: Optional[str],
    structured: dict[str, Optional[str]],
    project_id: Optional[str],
) -> bool:
    haystack = " ".join(
        part
        for part in [
            _normalize_text(title or ""),
            _normalize_text(message or ""),
            _normalize_text(assistant_output or ""),
            *(_normalize_text(value or "") for value in structured.values()),
        ]
        if part
    )
    if not haystack:
        return False
    if re.search(
        r"继续|实现|修复|修改|分析|排查|写|生成|搭建|部署|测试|重构|优化|迁移|清理|验证|跟进|推进|处理|完成|\b(fix|implement|debug|deploy|test|refactor|optimi[sz]e|migrat|clean up|verify|follow up|investigat|analy[sz]e|build|ship|complete|progress)\b",
        haystack,
        re.I,
    ):
        return True
    if project_id and any(_normalize_text(value or "") for value in structured.values()):
        return True
    return any(_normalize_text(value or "") for value in structured.values())


def evaluate_task_materialization(
    *,
    task_id: Optional[str],
    title: Optional[str],
    payload: TaskSummaryWriteRequest,
    structured: dict[str, Optional[str]],
) -> tuple[bool, str, str]:
    last_summary = structured.get("summary") or payload.summary
    task_kind = classify_task_kind(
        task_id=task_id,
        title=title,
        last_summary=last_summary,
        source_agent=payload.agent_id,
        project_id=payload.project_id,
    )
    if not governance_should_materialize_task(
        task_kind=task_kind,
        title=title,
        last_summary=last_summary,
    ):
        if task_kind != "work":
            return False, task_kind, f"task_kind:{task_kind}"
        return False, task_kind, "not_materializable"
    if is_task_lookup_question(payload.message or ""):
        return False, task_kind, "lookup_question"
    if not task_has_actionable_signal(
        title=title,
        message=payload.message,
        assistant_output=payload.assistant_output,
        structured=structured,
        project_id=payload.project_id,
    ):
        return False, task_kind, "not_actionable"
    return True, task_kind, "accepted"


__all__ = [
    "classify_task_kind",
    "compact_text",
    "derive_task_summary",
    "derive_task_title",
    "evaluate_task_materialization",
    "extract_task_lookup_subject",
    "humanize_task_id",
    "is_task_lookup_question",
    "make_task_id",
    "rewrite_keyword_soup_title",
    "rewrite_task_title_from_content",
    "sanitize_task_summary_preview",
    "sanitize_task_title",
    "split_sentences",
    "strip_markdown_noise",
    "summarize_title_candidate",
    "task_display_title",
    "task_has_actionable_signal",
    "task_subject_matches",
    "task_tokens",
]
