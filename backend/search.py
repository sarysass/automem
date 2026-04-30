"""Search-side query intent classification + vector query construction.

Pure-function module that decides:
- Whether a memory write/read is "current project state" vs "stable
  user-global context" (classify_legacy_memory_scope).
- What intent a search query is expressing (identity vs preference vs
  company vs task vs generic), and which categories to prefer/penalize
  (classify_query_intent).
- How to expand a vector query with intent-specific synonyms
  (build_vector_query).
- Which mixed-scope role split to apply when both user_global and
  project results are relevant (choose_mixed_scope_answer_roles).
- Whether the query is asking for historical/superseded facts
  (is_history_query).

Imports the shared category sets from backend.main (LONG_TERM_USER_*,
LONG_TERM_PROJECT_*, TASK_CATEGORIES) lazily to avoid a circular
import at module load.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.tasks import extract_task_lookup_subject, split_sentences


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _category_sets() -> tuple[set[str], set[str], set[str]]:
    """Resolve LONG_TERM_USER_CATEGORIES + LONG_TERM_PROJECT_CATEGORIES + TASK_CATEGORIES.

    Lazy lookup against backend.main keeps the module load order
    cycle-free: backend.main imports backend.search at module init, so
    we cannot eagerly read the category constants from it. By the time
    any function below executes, backend.main has finished loading and
    the sets are populated.
    """
    from backend import main as _main  # noqa: PLC0415 (lazy by design)

    return (
        _main.LONG_TERM_USER_CATEGORIES,
        _main.LONG_TERM_PROJECT_CATEGORIES,
        _main.TASK_CATEGORIES,
    )


def is_history_query(query: str) -> bool:
    normalized = _normalize_text(query).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"(历史|之前|以前|曾经|原来|旧版本|旧记录|history|historical|previous|earlier|former)",
            normalized,
            re.I,
        )
    )


def _looks_project_current_state_text(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"当前|现在|最近|本周|这周|下一步|接下来|进展|阻塞|handoff|blocker|workflow|正在|联调|执行状态|工作重心|主要在做",
            normalized,
            re.I,
        )
    )


def _looks_stable_or_index_text(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    if not normalized:
        return False
    return bool(
        re.search(
            r"^公司是|^项目是|核心目标|长期约束|稳定约束|长期决策|长期边界|项目背景|项目概述|项目地图|识别信息|身份是|姓名是|名字是|偏好使用",
            normalized,
            re.I,
        )
    )


def classify_legacy_memory_scope(
    *,
    text: str,
    metadata: Optional[dict[str, Any]] = None,
    run_id: Optional[str] = None,
    clustered_project: bool = False,
) -> dict[str, str]:
    long_term_user, long_term_project, task_categories = _category_sets()
    meta = metadata or {}
    category = _normalize_text(str(meta.get("category") or "")).lower()
    domain = _normalize_text(str(meta.get("domain") or "")).lower()
    project_id = _normalize_text(str(meta.get("project_id") or ""))
    task_id = _normalize_text(str(meta.get("task_id") or ""))
    normalized_run_id = _normalize_text(str(run_id or ""))

    if project_id:
        return {"scope": "project", "reason": "hard:project_id"}
    if task_id or normalized_run_id:
        return {"scope": "project", "reason": "hard:task_or_run_id"}
    if domain == "task" or category in task_categories:
        return {"scope": "project", "reason": "hard:task_domain"}

    if category in long_term_user:
        return {"scope": "user_global", "reason": "semantic:user_category"}

    if category in long_term_project:
        if _looks_project_current_state_text(text):
            return {"scope": "project", "reason": "semantic:project_current_state"}
        if _looks_stable_or_index_text(text):
            return {"scope": "user_global", "reason": "semantic:project_index_or_stable_context"}

    if clustered_project and _looks_project_current_state_text(text):
        return {"scope": "project", "reason": "aux:project_cluster"}

    if _looks_stable_or_index_text(text):
        return {"scope": "user_global", "reason": "semantic:stable_or_index_text"}
    if _looks_project_current_state_text(text):
        return {"scope": "project", "reason": "semantic:current_state_text"}

    return {"scope": "migration_review", "reason": "ambiguous"}


def choose_mixed_scope_answer_roles(intent: str) -> dict[str, str]:
    if intent in {"identity_lookup", "preference_lookup", "company_lookup"}:
        return {
            "main_scope": "user_global",
            "main_role": "cross_project_preferences_and_constraints",
            "supporting_scope": "project",
            "supporting_role": "current_project_state",
        }
    if intent == "task_lookup":
        return {
            "main_scope": "project",
            "main_role": "current_project_state",
            "supporting_scope": "user_global",
            "supporting_role": "cross_project_preferences_and_constraints",
        }
    return {
        "main_scope": "user_global",
        "main_role": "cross_project_preferences_and_constraints",
        "supporting_scope": "project",
        "supporting_role": "current_project_state",
    }


def classify_query_intent(query: str, filters: Optional[dict[str, Any]]) -> dict[str, Any]:
    long_term_user, long_term_project, task_categories = _category_sets()
    explicit_domain = (filters or {}).get("domain")
    normalized = _normalize_text(query).lower()

    def has_any(*patterns: str) -> bool:
        return any(re.search(pattern, normalized, re.I) for pattern in patterns)

    focus = "general"
    task_subject = ""

    if explicit_domain == "task":
        intent = "task_lookup"
        focus = "task"
    elif has_any(
        r"我(的)?名字",
        r"我叫",
        r"姓名",
        r"\bname\b",
        r"user'?s name",
        r"what(?:'s| is) (?:my|the user'?s) name",
        r"\bcalled\b",
    ):
        intent = "identity_lookup"
        focus = "name"
    elif has_any(r"身份", r"我是谁", r"什么身份", r"\brole\b", r"\btitle\b", r"\bceo\b", r"\bcto\b"):
        intent = "identity_lookup"
        focus = "role"
    elif has_any(r"什么语言", r"中文", r"英文", r"沟通", r"\blanguage\b", r"\bchinese\b", r"\benglish\b", r"\bcommunicat"):
        intent = "preference_lookup"
        focus = "language"
    elif has_any(r"偏好", r"风格", r"总结", r"简洁", r"直接", r"\bpreference\b", r"\bstyle\b", r"\bsummary\b", r"\bconcise\b", r"\bdirect\b"):
        intent = "preference_lookup"
        focus = "style"
    elif has_any(r"公司", r"example", r"项目背景", r"团队", r"组织", r"企业", r"\bcompany\b", r"\bteam\b", r"\borganization\b", r"workflow", r"memory hub", r"codex", r"openclaw"):
        intent = "company_lookup"
        focus = "company"
    elif has_any(r"下一步", r"接下来", r"任务", r"进展", r"阻塞", r"handoff", r"blocker", r"next action", r"继续"):
        intent = "task_lookup"
        focus = "task"
        task_subject = extract_task_lookup_subject(query)
    else:
        intent = "generic_memory_search"

    if explicit_domain:
        effective_domain = explicit_domain
    elif intent == "task_lookup":
        effective_domain = "task"
    else:
        effective_domain = "long_term"

    preferred_categories: set[str] = set()
    exact_terms: list[str] = []
    penalized_categories: set[str] = set()

    if intent == "identity_lookup":
        preferred_categories = {"user_profile"}
        if focus == "name":
            exact_terms = ["姓名", "名字", "我叫", "称呼", "name", "user name", "called"]
        elif focus == "role":
            exact_terms = ["身份", "角色", "role", "title", "ceo", "cto", "创始人", "负责人"]
        penalized_categories = task_categories
    elif intent == "preference_lookup":
        preferred_categories = {"preference"}
        if focus == "language":
            exact_terms = ["中文", "英文", "语言", "沟通", "language", "communicate", "chinese", "english"]
        else:
            exact_terms = ["偏好", "总结", "风格", "简洁", "直接", "preference", "style", "summary", "concise", "direct"]
        penalized_categories = task_categories
    elif intent == "company_lookup":
        preferred_categories = {"project_context"}
        exact_terms = ["公司", "example", "项目", "团队", "组织", "企业", "company", "organization", "team"]
        penalized_categories = task_categories
    elif intent == "task_lookup":
        preferred_categories = task_categories
        exact_terms = ["下一步", "任务", "进展", "阻塞", "handoff", "blocker", "next", "todo"]
        if task_subject:
            exact_terms.extend(split_sentences(task_subject) or [task_subject])
        penalized_categories = long_term_user | long_term_project
    else:
        preferred_categories = long_term_user | long_term_project
        penalized_categories = set()

    query_variants = [_normalize_text(query)]
    query_variants.extend(term for term in exact_terms if term not in query_variants)

    return {
        "intent": intent,
        "focus": focus,
        "effective_domain": effective_domain,
        "task_subject": task_subject,
        "preferred_categories": preferred_categories,
        "penalized_categories": penalized_categories,
        "query_variants": [variant for variant in query_variants if variant],
    }


def build_vector_query(query: str, profile: dict[str, Any]) -> str:
    normalized = _normalize_text(query)
    variants = [_normalize_text(item) for item in profile.get("query_variants") or [] if _normalize_text(item)]
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        lowered = value.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        ordered.append(value)

    if normalized:
        add(normalized)

    intent = profile.get("intent")
    focus = profile.get("focus")
    if intent == "identity_lookup":
        add("user profile")
        if focus == "name":
            add("姓名 名字 我叫 称呼")
            add("name user name called")
        elif focus == "role":
            add("身份 角色 CEO 创始人")
            add("role title CEO founder")
    elif intent == "preference_lookup":
        add("user preference")
        if focus == "language":
            add("中文 英文 语言 沟通")
            add("language communicate chinese english")
        else:
            add("偏好 风格 总结 简洁 直接")
            add("preference style summary concise direct")
    elif intent == "company_lookup":
        add("project context")
        add("公司 团队 项目背景")
        add("company team organization project context")
    elif intent == "task_lookup":
        add("task progress next action")
        add("下一步 任务 进展 阻塞")
        if profile.get("task_subject"):
            add(str(profile["task_subject"]))

    for variant in variants:
        add(variant)
    return " ".join(ordered)


__all__ = [
    "build_vector_query",
    "choose_mixed_scope_answer_roles",
    "classify_legacy_memory_scope",
    "classify_query_intent",
    "is_history_query",
]
