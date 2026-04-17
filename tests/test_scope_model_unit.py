from __future__ import annotations


def test_classify_legacy_memory_scope_prefers_project_for_hard_structural_evidence(backend_module):
    result = backend_module.classify_legacy_memory_scope(
        text="下一步是验证筛选交互和空状态文案。",
        metadata={"domain": "task", "category": "next_action", "task_id": "task_frontend-panel"},
    )
    assert result == {"scope": "project", "reason": "hard:task_or_run_id"}


def test_classify_legacy_memory_scope_routes_stable_preference_to_user_global(backend_module):
    result = backend_module.classify_legacy_memory_scope(
        text="偏好使用中文沟通",
        metadata={"domain": "long_term", "category": "preference"},
    )
    assert result == {"scope": "user_global", "reason": "semantic:user_category"}


def test_classify_legacy_memory_scope_routes_project_overview_to_user_global(backend_module):
    result = backend_module.classify_legacy_memory_scope(
        text="公司是Example Corp",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    assert result == {"scope": "user_global", "reason": "semantic:project_index_or_stable_context"}


def test_classify_legacy_memory_scope_routes_current_project_state_to_project(backend_module):
    result = backend_module.classify_legacy_memory_scope(
        text="当前工作重心是推进 automem 的 Phase 11 回归测试。",
        metadata={"domain": "long_term", "category": "project_context"},
        clustered_project=True,
    )
    assert result["scope"] == "project"
    assert result["reason"] in {"semantic:project_current_state", "aux:project_cluster"}


def test_classify_legacy_memory_scope_uses_migration_review_for_weak_evidence(backend_module):
    result = backend_module.classify_legacy_memory_scope(
        text="跟进一下这个事情。",
        metadata={"domain": "long_term", "category": "project_context"},
    )
    assert result == {"scope": "migration_review", "reason": "ambiguous"}


def test_choose_mixed_scope_answer_roles_prefers_global_for_preference_intent(backend_module):
    result = backend_module.choose_mixed_scope_answer_roles("preference_lookup")
    assert result["main_scope"] == "user_global"
    assert result["main_role"] == "cross_project_preferences_and_constraints"
    assert result["supporting_scope"] == "project"


def test_choose_mixed_scope_answer_roles_prefers_project_for_task_intent(backend_module):
    result = backend_module.choose_mixed_scope_answer_roles("task_lookup")
    assert result["main_scope"] == "project"
    assert result["main_role"] == "current_project_state"
    assert result["supporting_scope"] == "user_global"
