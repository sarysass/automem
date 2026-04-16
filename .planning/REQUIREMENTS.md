# Requirements

**Coverage:** 13/13 satisfied, 0 pending gap closure

## Requirement Checklist

- [x] `AUTH-01` Secure Defaults
  服务未显式配置认证时，不得以匿名管理员模式启动或放行业务请求。

- [x] `AUTH-02` Tenant Binding
  非管理员 API key 必须绑定 `user_id`，避免不同用户数据混写到共享身份。

- [x] `GOV-01` Backend-Owned Governance
  自动 capture 的长期记忆 / task 判断以 backend 为唯一决策点，adapter 只保留轻量抑制。

- [x] `CONS-01` Fresh Cache Before Maintenance
  `tasks/normalize` 和 `consolidate` 必须先基于最新后端状态刷新 `memory_cache`。

- [x] `CONS-02` Safe Canonical Rewrite
  `consolidate` 的 canonical rewrite 必须先写入新记录，再删除旧记录，避免失败时数据丢失。

- [x] `IAM-01` Shared Visibility Model
  memory 与 task 的身份模型必须支持超越 `user_id` 的共享协作边界，至少可表达 `project` 级 scope，并为后续 `team/org` 扩展留出结构。

- [x] `IAM-02` Consistent Access Enforcement
  memory 与 task 的读写权限必须使用同一套 identity / visibility 规则，避免“memory 能看见但 task 看不见”或相反。

- [x] `RET-01` Hybrid Retrieval
  检索必须组合 semantic recall、lexical/FTS 命中与 metadata filters，而不是仅依赖单一路径。

- [x] `RET-02` Explainable Recall
  每条召回结果都必须带有结构化解释信息，至少包含命中方式、来源和当前生命周期状态。

- [x] `FACT-01` Temporal Fact Lifecycle
  长期记忆必须能表达事实的生效、失效、替代和历史版本关系，而不是只追加新文本。

- [x] `FACT-02` Conflict Governance
  对同一事实位点的矛盾信息必须被检测、标记并进入显式治理流程，而不是静默共存。

- [x] `OPS-01` Split Hot And Background Paths
  admission / route 必须保持轻量；canonicalize、merge、conflict resolution、fact closure 等重治理逻辑应在后台 worker 中执行。

- [x] `OPS-02` API Worker MCP Control Plane
  系统运行形态需要清晰拆分为 API、governance worker 与 MCP/distribution 接入面，便于扩展与运维。

## Traceability

| REQ-ID | Description | Phase | Priority | Status |
|-------|-------------|-------|----------|--------|
| AUTH-01 | Secure defaults | 08 | must | Satisfied |
| AUTH-02 | Tenant binding | 08 | must | Satisfied |
| GOV-01 | Backend-owned governance | 08 | must | Satisfied |
| CONS-01 | Fresh cache before maintenance | 08 | must | Satisfied |
| CONS-02 | Safe canonical rewrite | 08 | must | Satisfied |
| IAM-01 | Shared visibility model | 04 | must | Satisfied |
| IAM-02 | Consistent access enforcement | 04 | must | Satisfied |
| RET-01 | Hybrid retrieval | 05 | must | Satisfied |
| RET-02 | Explainable recall | 05 | must | Satisfied |
| FACT-01 | Temporal fact lifecycle | 06 | must | Satisfied |
| FACT-02 | Conflict governance | 06 | must | Satisfied |
| OPS-01 | Split hot and background paths | 07 | must | Satisfied |
| OPS-02 | API worker MCP control plane | 07 | must | Satisfied |

## Audit Notes

- Phase `08` 已恢复 foundational requirement 的证据链，不再只是 summary 声明完成：
  - `AUTH-01`、`AUTH-02` 的证据来源是 `.planning/phases/01-auth-defaults-and-tenant-isolation/01-VERIFICATION.md`
  - `GOV-01` 的证据来源是 `.planning/phases/02-centralize-memory-governance/02-VERIFICATION.md`
  - `CONS-01`、`CONS-02` 的证据来源是 `.planning/phases/03-stabilize-cache-and-consolidation/03-VERIFICATION.md`
- 因此这 5 个 requirements 已从 Phase `08` 的 gap closure 回到 `Satisfied`，不再作为 milestone audit 的 orphaned gaps。
- Milestone 级 `*-VALIDATION.md` / Nyquist 覆盖仍然缺失，这部分验证债继续由 Phase `09` 关闭，但不单独新增 requirement ID。
