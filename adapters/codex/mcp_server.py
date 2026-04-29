from __future__ import annotations

from contextlib import asynccontextmanager
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

from client import AutomemClient


@asynccontextmanager
async def _client_lifespan(_: FastMCP):
    try:
        yield {}
    finally:
        client.close()


mcp = FastMCP(
    name="automem-memory",
    instructions=(
        "Use this server to access shared persistent memory. "
        "Prefer search before asking the user to repeat stable preferences, "
        "project rules, or task handoff state. Store only durable, reusable "
        "information; do not store chain-of-thought or transient reasoning."
    ),
    lifespan=_client_lifespan,
)
client = AutomemClient()


def _defaults() -> dict[str, Any]:
    return client.defaults


def _normalize_domain(domain: str) -> str:
    aliases = {
        "user": "long_term",
        "long_term": "long_term",
        "long-term": "long_term",
        "project": "long_term",
        "agent": "agent",
        "task": "task",
    }
    normalized = aliases.get(domain)
    if not normalized:
        raise ValueError("domain must be one of: long_term, user, project, agent, task")
    return normalized


def _normalize_scope_name(scope: str) -> str:
    aliases = {
        "user": "long_term",
        "long_term": "long_term",
        "long-term": "long_term",
        "project": "long_term",
        "agent": "agent",
        "task": "task",
    }
    normalized = aliases.get(scope)
    if not normalized:
        raise ValueError("scope must be one of: long_term, user, project, agent, task")
    return normalized


def _matches_filters(
    item: dict[str, Any],
    *,
    project_id: str | None,
    category: str | None,
    domain: str | None = None,
) -> bool:
    metadata = item.get("metadata") or {}
    if domain and metadata.get("domain") != domain:
        return False
    if project_id and metadata.get("project_id") != project_id:
        return False
    if category and metadata.get("category") != category:
        return False
    return True


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_explicit_long_term_request(text: str) -> bool:
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


def _split_explicit_items(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    lines = [line.strip() for line in normalized.split("\n")]
    items: list[str] = []
    capture = False
    for line in lines:
        if not line:
            continue
        if _is_explicit_long_term_request(line):
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


def _infer_long_term_category(text: str) -> str | None:
    lower = text.lower()
    if re.search(r"姓名|名字|我叫|prefer|喜欢|偏好|习惯|中文|英文|summary|简洁|直接", lower):
        return "user_profile" if re.search(r"姓名|名字|我叫", lower) else "preference"
    if re.search(r"公司|团队|内部|业务|项目|产品|repo|backend|workflow|automem|codex|openclaw", lower):
        return "project_context"
    if re.search(r"规则|约束|必须|只能|不要|不应|should|must|never|always|private access", lower):
        return "project_rule"
    if re.search(r"架构|方案|决定|采用|使用|we use|decision|architecture", lower):
        return "architecture_decision"
    return None


def _canonicalize_explicit_long_term_item(item: str) -> list[dict[str, str]]:
    text = _normalize_text(re.sub(r"^(请记住|记住)[:：]?\s*", "", item))
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
        r"(?:我是|身份是)\s*([A-Za-z][A-Za-z0-9_-]*|CEO|CTO|COO|CFO|Founder|创始人|负责人|CEO。?)",
        text,
        re.IGNORECASE,
    )
    if role_match:
        role = role_match.group(1).rstrip("。")
        add(f"身份是{role}", "user_profile")

    if not out:
        inferred = _infer_long_term_category(text)
        if inferred:
            add(text, inferred)

    return out


def _extract_long_term_entries(text: str, category: str | None) -> list[dict[str, str]]:
    raw_text = text
    normalized = _normalize_text(text)
    if not normalized:
        return []

    if category:
        items = _split_explicit_items(raw_text) if _is_explicit_long_term_request(raw_text) else [normalized]
        return [{"text": item, "category": category} for item in items if item]

    entries: list[dict[str, str]] = []
    if _is_explicit_long_term_request(raw_text):
        for item in _split_explicit_items(raw_text):
            entries.extend(_canonicalize_explicit_long_term_item(item))
    else:
        inferred = _infer_long_term_category(normalized)
        if inferred:
            entries.append({"text": normalized, "category": inferred})

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["text"], entry["category"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _store_route_result(
    *,
    route_result: dict[str, Any],
    user_id: str,
    agent_id: str,
    project_id: str | None,
    message: str,
    assistant_output: str | None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    stored_long_term: list[dict[str, Any]] = []
    stored_task: dict[str, Any] | None = None

    if route_result.get("route") in {"long_term", "mixed"}:
        entries = route_result.get("entries") or route_result.get("long_term") or []
        for entry in entries:
            entry_metadata = {
                "domain": "long_term",
                "source_agent": agent_id,
                "category": entry.get("category"),
            }
            if project_id or entry.get("project_id"):
                entry_metadata["project_id"] = entry.get("project_id") or project_id
            stored_long_term.append(
                client.store(
                    text=entry["text"],
                    user_id=user_id,
                    metadata=entry_metadata,
                    infer=False,
                )
            )

    if route_result.get("route") in {"task", "mixed"} and route_result.get("task"):
        task = route_result["task"]
        summary = task.get("summary") or {}
        stored_task = client.store_task_summary(
            user_id=user_id,
            agent_id=agent_id,
            project_id=project_id,
            task_id=task.get("task_id"),
            title=task.get("title"),
            summary=summary.get("summary"),
            progress=summary.get("progress"),
            blocker=summary.get("blocker"),
            next_action=summary.get("next_action"),
            message=message,
            assistant_output=assistant_output,
            session_id=session_id,
            channel=channel,
        )

    return {
        "route": route_result.get("route"),
        "stored_long_term": stored_long_term,
        "stored_task": stored_task,
        "reason": route_result.get("reason"),
    }


@mcp.tool(
    name="memory_health",
    description="Check whether the shared memory service is reachable and report current defaults.",
)
def memory_health() -> dict[str, Any]:
    status = client.healthz()
    return {"service": status, "defaults": _defaults()}


@mcp.tool(
    name="memory_search",
    description="Search shared persistent memory for preferences, project rules, and task handoff notes.",
)
def memory_search(
    query: str,
    scope: str = "long_term",
    task_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    effective_user_id = user_id or defaults["user_id"]
    effective_agent_id = agent_id or defaults["agent_id"]
    effective_project_id = project_id or defaults["project_id"]
    expanded_limit = max(defaults["top_k"] * 4, 20)
    scope = _normalize_scope_name(scope)

    if scope == "task" and not task_id:
        resolution = client.resolve_task(
            user_id=effective_user_id,
            message=query,
            agent_id=effective_agent_id,
            project_id=effective_project_id,
            session_id=session_id,
            channel=channel,
        )
        task_id = resolution.get("task_id")
        if resolution.get("action") == "no_task" or not task_id:
            return {
                "scope": scope,
                "query": query,
                "project_id": effective_project_id,
                "category": category,
                "results": [],
                "resolution": resolution,
            }

    if scope == "long_term":
        result = client.search(
            query=query,
            user_id=effective_user_id,
            filters={"domain": "long_term"},
            limit=expanded_limit,
        )
    elif scope == "agent":
        result = client.search(
            query=query,
            user_id=effective_user_id,
            agent_id=effective_agent_id,
            filters={"domain": "agent"},
            limit=expanded_limit,
        )
    else:
        result = client.search(
            query=query,
            user_id=effective_user_id,
            run_id=task_id,
            filters={"domain": "task"},
            limit=expanded_limit,
        )

    filtered = [
        item
        for item in result.get("results", [])
        if float(item.get("score", 1.0)) >= defaults["search_threshold"]
        and _matches_filters(
            item,
            project_id=effective_project_id,
            category=category,
            domain=scope if scope in {"long_term", "task", "agent"} else None,
        )
    ]
    return {
        "scope": scope,
        "query": query,
        "project_id": effective_project_id,
        "category": category,
        "candidate_limit": expanded_limit,
        "results": filtered[: defaults["top_k"]],
    }


@mcp.tool(
    name="memory_store",
    description="Store durable memory. Use for stable preferences, project rules, or task handoff summaries.",
)
def memory_store(
    text: str,
    domain: str = "long_term",
    task_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    effective_user_id = user_id or defaults["user_id"]
    effective_agent_id = agent_id or defaults["agent_id"]
    effective_project_id = project_id or defaults["project_id"]
    domain = _normalize_domain(domain)

    metadata: dict[str, Any] = {"domain": domain, "source_agent": effective_agent_id}
    if effective_project_id:
        metadata["project_id"] = effective_project_id
    if category:
        metadata["category"] = category
    if task_id:
        metadata["task_id"] = task_id

    if domain == "long_term":
        normalized = _normalize_text(text)
        if not normalized:
            raise ValueError("text must not be empty")
        if category:
            return client.store(
                text=normalized,
                user_id=effective_user_id,
                metadata=metadata,
                infer=False,
            )
        if not hasattr(client, "memory_route"):
            entries = _extract_long_term_entries(text, category)
            if not entries:
                entries = [{"text": normalized}]
            responses: list[dict[str, Any]] = []
            results: list[dict[str, Any]] = []
            for entry in entries:
                entry_metadata = dict(metadata)
                entry_category = entry.get("category")
                if entry_category:
                    entry_metadata["category"] = entry_category
                response = client.store(
                    text=entry["text"],
                    user_id=effective_user_id,
                    metadata=entry_metadata,
                    infer=False,
                )
                responses.append(response)
                results.extend(response.get("results", []))
            if len(responses) == 1:
                return responses[0]
            return {
                "status": "stored" if results else "skipped",
                "results": results,
                "stored_count": len(results),
                "responses": responses,
            }
        route_result = client.memory_route(
            user_id=effective_user_id,
            message=normalized,
            agent_id=effective_agent_id,
            project_id=effective_project_id,
            assistant_output=None,
            client_hints={
                "explicit_long_term": True,
                "source": "codex",
            },
        )
        if route_result.get("route") == "drop":
            return route_result
        return _store_route_result(
            route_result=route_result,
            user_id=effective_user_id,
            agent_id=effective_agent_id,
            project_id=effective_project_id,
            message=normalized,
            assistant_output=None,
        )
    if domain == "agent":
        return client.store(
            text=text,
            user_id=effective_user_id,
            agent_id=effective_agent_id,
            metadata=metadata,
            infer=False,
        )
    if domain == "task":
        if not task_id:
            raise ValueError("task_id is required when domain=task")
        return client.store(
            text=text,
            user_id=effective_user_id,
            agent_id=effective_agent_id,
            run_id=task_id,
            metadata=metadata,
            infer=False,
        )
    raise ValueError("domain must be one of: long_term, user, project, agent, task")


@mcp.tool(
    name="memory_route",
    description="Ask the centralized router whether content should be dropped, stored as long-term memory, task memory, or both.",
)
def memory_route(
    message: str,
    assistant_output: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    explicit_long_term: bool = False,
    task_like: bool | None = None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    return client.memory_route(
        user_id=user_id or defaults["user_id"],
        message=message,
        agent_id=agent_id or defaults["agent_id"],
        project_id=project_id or defaults["project_id"],
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
        client_hints={
            "explicit_long_term": explicit_long_term,
            "source": "codex",
            **({"task_like": True} if task_like is True else {}),
        },
    )


@mcp.tool(
    name="memory_capture",
    description="Route and store long-term and/or task memory in one step.",
)
def memory_capture(
    message: str,
    assistant_output: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    explicit_long_term: bool = False,
    task_like: bool | None = None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    effective_user_id = user_id or defaults["user_id"]
    effective_agent_id = agent_id or defaults["agent_id"]
    effective_project_id = project_id or defaults["project_id"]
    route_result = client.memory_route(
        user_id=effective_user_id,
        message=message,
        agent_id=effective_agent_id,
        project_id=effective_project_id,
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
        client_hints={
            "explicit_long_term": explicit_long_term,
            "source": "codex",
            **({"task_like": True} if task_like is True else {}),
        },
    )
    if route_result.get("route") == "drop":
        return route_result
    return _store_route_result(
        route_result=route_result,
        user_id=effective_user_id,
        agent_id=effective_agent_id,
        project_id=effective_project_id,
        message=message,
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
    )


@mcp.tool(name="task_resolve", description="Resolve whether the current turn belongs to an existing task, a new task, or no task.")
def task_resolve(
    message: str,
    assistant_output: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    return client.resolve_task(
        user_id=user_id or defaults["user_id"],
        message=message,
        agent_id=agent_id or defaults["agent_id"],
        project_id=project_id or defaults["project_id"],
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
    )


@mcp.tool(name="task_summary_store", description="Store a structured task summary in the centralized task registry.")
def task_summary_store(
    message: str,
    assistant_output: str | None = None,
    summary: str | None = None,
    progress: str | None = None,
    blocker: str | None = None,
    next_action: str | None = None,
    task_id: str | None = None,
    title: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    return client.store_task_summary(
        user_id=user_id or defaults["user_id"],
        agent_id=agent_id or defaults["agent_id"],
        project_id=project_id or defaults["project_id"],
        task_id=task_id,
        title=title,
        summary=summary,
        progress=progress,
        blocker=blocker,
        next_action=next_action,
        message=message,
        assistant_output=assistant_output,
        session_id=session_id,
        channel=channel,
    )


@mcp.tool(name="task_list", description="List active or historical tasks from the centralized task registry.")
def task_list(
    user_id: str | None = None,
    project_id: str | None = None,
    status: str | None = "active",
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    defaults = _defaults()
    return client.list_tasks(
        user_id=user_id or defaults["user_id"],
        project_id=project_id or defaults["project_id"],
        status=status,
        limit=limit,
        cursor=cursor,
    )


@mcp.tool(name="task_get", description="Fetch a single task from the centralized task registry.")
def task_get(task_id: str) -> dict[str, Any]:
    return client.get_task(task_id)


@mcp.tool(name="task_close", description="Close a task in the centralized task registry.")
def task_close(task_id: str, reason: str | None = None) -> dict[str, Any]:
    return client.close_task(task_id, reason=reason)


@mcp.tool(name="task_archive", description="Archive a task in the centralized task registry.")
def task_archive(task_id: str, reason: str | None = None) -> dict[str, Any]:
    return client.archive_task(task_id, reason=reason)


@mcp.tool(name="memory_metrics", description="Fetch basic memory metrics and route statistics.")
def memory_metrics() -> dict[str, Any]:
    return client.metrics()


@mcp.tool(name="memory_consolidate", description="Run baseline consolidation for long-term memory and tasks.")
def memory_consolidate(dry_run: bool = True) -> dict[str, Any]:
    return client.consolidate(dry_run=dry_run)


@mcp.tool(name="memory_list", description="List stored memories for the current user, agent, or task scope.")
def memory_list(
    scope: str = "long_term",
    task_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    defaults = _defaults()
    effective_user_id = user_id or defaults["user_id"]
    effective_agent_id = agent_id or defaults["agent_id"]
    effective_project_id = project_id or defaults["project_id"]
    scope = _normalize_scope_name(scope)

    if scope == "long_term":
        memories = client.list_memories(user_id=effective_user_id)
        return [item for item in memories if _matches_filters(item, project_id=effective_project_id, category=category)]
    if scope == "agent":
        memories = client.list_memories(user_id=effective_user_id, agent_id=effective_agent_id)
        return [item for item in memories if _matches_filters(item, project_id=effective_project_id, category=category)]
    if scope == "task":
        if not task_id:
            raise ValueError("task_id is required when scope=task")
        memories = client.list_memories(user_id=effective_user_id, agent_id=effective_agent_id, run_id=task_id)
        return [item for item in memories if _matches_filters(item, project_id=effective_project_id, category=category)]
    raise ValueError("scope must be one of: long_term, user, project, agent, task")


@mcp.tool(name="memory_get", description="Fetch one stored memory by id.")
def memory_get(memory_id: str) -> dict[str, Any]:
    return client.get_memory(memory_id)


@mcp.tool(name="memory_forget", description="Delete one stored memory by id.")
def memory_forget(memory_id: str) -> dict[str, Any]:
    return client.forget(memory_id)


if __name__ == "__main__":
    mcp.run()
