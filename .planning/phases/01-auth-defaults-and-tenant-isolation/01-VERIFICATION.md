---
status: passed
phase: 01-auth-defaults-and-tenant-isolation
requirements: [AUTH-01, AUTH-02]
completed: 2026-04-16
---

# Phase 01 Verification

## Outcome

Phase 01 passes automated verification.

## Requirements Coverage

### AUTH-01 Secure Defaults

- `backend/main.py` 在 `verify_api_key` 中要求所有受保护请求都携带 `X-API-Key`，缺失时直接返回 `401` 和 `X-API-Key header is required`，不再存在匿名管理员兜底。
- 同一函数会在 key 不存在或失效时返回 `401` 和 `Invalid API key`，证明服务默认是 fail-closed，而不是在认证配置缺失时放行业务请求。
- `tests/test_backend_baseline.py` 里的 `test_missing_api_key_requires_header` 与 `test_invalid_api_key_is_rejected` 覆盖了这两条负向路径。

### AUTH-02 Tenant Binding

- `backend/main.py` 的 `verify_api_key` 要求所有非 admin key 必须带 `user_id`，否则返回 `403` 和 `Non-admin API keys must be bound to a user_id`。
- `backend/main.py` 的 `/agent-keys` 创建入口也会提前拒绝无 `user_id` 的非 admin key，请求返回 `400` 和 `Non-admin API keys require user_id`。
- `tests/test_backend_baseline.py` 中的 `test_agent_keys_reject_non_admin_without_user_binding`、`test_unbound_non_admin_api_key_is_rejected_at_verification`，以及既有的 `test_agent_key_enforces_bound_agent_identity` 一起证明了创建阶段和运行时验证阶段都不会接受未绑定用户的非 admin key。

## Automated Evidence

- `./.venv/bin/python -m pytest tests/test_backend_baseline.py::test_missing_api_key_requires_header tests/test_backend_baseline.py::test_invalid_api_key_is_rejected tests/test_backend_baseline.py::test_agent_keys_reject_non_admin_without_user_binding tests/test_backend_baseline.py::test_unbound_non_admin_api_key_is_rejected_at_verification tests/test_backend_baseline.py::test_agent_key_enforces_bound_agent_identity`
  Result: `5 passed in 0.35s`

## Must-Haves

- [x] 缺少认证头或非法 key 的请求会被拒绝，而不是匿名放行。
- [x] 非 admin key 在创建和验证两个阶段都必须绑定具体 `user_id`。
- [x] 认证相关负向路径有独立 regression tests，可重复运行。

## Gaps

None.

## Human Verification

None required.
