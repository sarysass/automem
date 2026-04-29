from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass
class BenchmarkCase:
    name: str
    payload: dict[str, Any]
    expected_top1: str | None = None
    expected_empty: bool = False


DEFAULT_CASES: list[BenchmarkCase] = [
    BenchmarkCase("名字-完整问句", {"query": "我的名字叫什么", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-简短问句", {"query": "我叫什么", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-关键词", {"query": "姓名", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-人名", {"query": "示例用户", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-英文完整问句", {"query": "what is my name", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-英文用户问句", {"query": "what is the user's name", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-英文短关键词", {"query": "user name", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("名字-中英混合", {"query": "name 名字 我叫", "user_id": "example-user"}, expected_top1="姓名是示例用户"),
    BenchmarkCase("公司-完整问句", {"query": "我的公司是什么", "user_id": "example-user"}, expected_top1="公司是Example Corp"),
    BenchmarkCase("公司-短关键词", {"query": "Example", "user_id": "example-user"}, expected_top1="公司是Example Corp"),
    BenchmarkCase("公司-英文完整问句", {"query": "what is my company", "user_id": "example-user"}, expected_top1="公司是Example Corp"),
    BenchmarkCase("公司-英文关键词", {"query": "company", "user_id": "example-user"}, expected_top1="公司是Example Corp"),
    BenchmarkCase("身份-关键词", {"query": "身份", "user_id": "example-user"}, expected_top1="身份是CEO"),
    BenchmarkCase("身份-角色词", {"query": "CEO", "user_id": "example-user"}, expected_top1="身份是CEO"),
    BenchmarkCase("身份-英文完整问句", {"query": "what is my role", "user_id": "example-user"}, expected_top1="身份是CEO"),
    BenchmarkCase("身份-英文关键词", {"query": "role", "user_id": "example-user"}, expected_top1="身份是CEO"),
    BenchmarkCase("语言-完整问句", {"query": "请用什么语言和我沟通", "user_id": "example-user"}, expected_top1="偏好使用中文沟通"),
    BenchmarkCase("语言-偏好问句", {"query": "我喜欢什么语言", "user_id": "example-user"}, expected_top1="偏好使用中文沟通"),
    BenchmarkCase("语言-关键词", {"query": "中文", "user_id": "example-user"}, expected_top1="偏好使用中文沟通"),
    BenchmarkCase("语言-英文完整问句", {"query": "what language should you use with me", "user_id": "example-user"}, expected_top1="偏好使用中文沟通"),
    BenchmarkCase("语言-英文关键词", {"query": "language", "user_id": "example-user"}, expected_top1="偏好使用中文沟通"),
    BenchmarkCase("总结风格-关键词", {"query": "简洁直接的总结", "user_id": "example-user"}, expected_top1="偏好简洁直接的总结"),
    BenchmarkCase("总结风格-英文关键词", {"query": "concise direct summary", "user_id": "example-user"}, expected_top1="偏好简洁直接的总结"),
    BenchmarkCase("偏好-泛查询", {"query": "偏好", "user_id": "example-user"}, expected_top1="偏好"),
    BenchmarkCase("任务-通用下一步", {"query": "下一步是什么", "user_id": "example-user"}, expected_top1="下一步"),
    BenchmarkCase("任务-主题查询", {"query": "共享记忆系统任务", "user_id": "example-user"}, expected_top1="下一步"),
    BenchmarkCase("任务-无关主题", {"query": "视频压缩方案的下一步是什么", "user_id": "example-user"}, expected_empty=True),
    BenchmarkCase("管理员-无用户短关键词", {"query": "Example"}, expected_top1="公司是Example Corp"),
]


def post_json(base_url: str, path: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + path,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def run_case(base_url: str, api_key: str, case: BenchmarkCase) -> dict[str, Any]:
    payload = dict(case.payload)
    payload.setdefault("limit", 25)
    result = post_json(base_url, "/v1/search", api_key, payload)
    top1 = (result.get("results") or [{}])[0].get("memory") if result.get("results") else None
    passed = False
    if case.expected_empty:
        passed = not bool(result.get("results"))
    elif case.expected_top1 is not None and top1 is not None:
        passed = case.expected_top1 in top1
    return {
        "name": case.name,
        "payload": payload,
        "expected_top1": case.expected_top1,
        "expected_empty": case.expected_empty,
        "meta": result.get("meta", {}),
        "top1": top1,
        "result_count": len(result.get("results") or []),
        "passed": passed,
    }


def render_markdown(results: list[dict[str, Any]], *, base_url: str) -> str:
    passed_count = sum(1 for item in results if item["passed"])
    lines = [
        "# Memory Retrieval Benchmark",
        "",
        f"- Base URL: `{base_url}`",
        f"- Cases: `{len(results)}`",
        f"- Passed: `{passed_count}/{len(results)}`",
        "",
        "| Case | Passed | Intent | Domain | Top1 | Count |",
        "|---|---|---|---|---|---|",
    ]
    for item in results:
        meta = item.get("meta") or {}
        intent = meta.get("intent", "")
        domain = meta.get("effective_domain", "")
        top1 = (item.get("top1") or "").replace("\n", " ")
        if len(top1) > 60:
            top1 = top1[:57] + "..."
        lines.append(
            f"| {item['name']} | {'yes' if item['passed'] else 'no'} | {intent} | {domain} | {top1} | {item['result_count']} |"
        )
    lines.extend(["", "## Raw Results", "", "```json", json.dumps(results, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fixed recall benchmark against the memory API.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--output", help="Optional markdown output path.")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in DEFAULT_CASES:
        try:
            result = run_case(args.base_url, args.api_key, case)
        except error.HTTPError as exc:
            result = {
                "name": case.name,
                "payload": case.payload,
                "expected_top1": case.expected_top1,
                "expected_empty": case.expected_empty,
                "meta": {},
                "top1": None,
                "result_count": 0,
                "passed": False,
                "error": f"HTTP {exc.code}",
            }
        except Exception as exc:  # pragma: no cover - benchmark utility fallback
            result = {
                "name": case.name,
                "payload": case.payload,
                "expected_top1": case.expected_top1,
                "expected_empty": case.expected_empty,
                "meta": {},
                "top1": None,
                "result_count": 0,
                "passed": False,
                "error": repr(exc),
            }
        results.append(result)
        if not result["passed"]:
            failures.append(case.name)

    markdown = render_markdown(results, base_url=args.base_url)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
