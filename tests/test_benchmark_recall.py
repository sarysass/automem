from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "backend" / "benchmark_recall.py"
SPEC = importlib.util.spec_from_file_location("benchmark_recall_for_test", MODULE_PATH)
benchmark_recall = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = benchmark_recall
SPEC.loader.exec_module(benchmark_recall)


def test_default_cases_cover_cross_lingual_queries():
    names = {case.name for case in benchmark_recall.DEFAULT_CASES}
    assert "名字-英文完整问句" in names
    assert "名字-英文用户问句" in names
    assert "公司-英文完整问句" in names
    assert "身份-英文完整问句" in names
    assert "语言-英文完整问句" in names
    assert "总结风格-英文关键词" in names


def test_run_case_sets_default_limit(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post_json(base_url: str, path: str, api_key: str, payload: dict[str, object]):
        captured["payload"] = payload
        return {"results": [{"memory": "姓名是示例用户"}], "meta": {"intent": "identity_lookup"}}

    monkeypatch.setattr(benchmark_recall, "post_json", fake_post_json)

    result = benchmark_recall.run_case(
        "http://example.test",
        "test-key",
        benchmark_recall.BenchmarkCase(
            "名字-英文完整问句",
            {"query": "what is my name", "user_id": "example-user"},
            expected_top1="姓名是示例用户",
        ),
    )

    assert result["passed"] is True
    assert captured["payload"]["limit"] == 25
