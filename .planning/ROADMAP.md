# Roadmap: automem

## Overview

automem is evolving from foundational memory hardening into a shared memory control plane for multi-agent systems. The next milestone focuses on four product upgrades distilled from prior research: shared identity and access boundaries, hybrid retrieval with explainability, temporal fact lifecycle with conflict governance, and a clearer runtime split between API, worker, and MCP distribution surfaces.

## Phases

- [x] **Phase 01: Auth Defaults And Tenant Isolation** - Remove fail-open auth behavior and bind non-admin API keys to real users.
- [x] **Phase 02: Centralize Memory Governance** - Make backend governance the single decision point for memory and task admission.
- [x] **Phase 03: Stabilize Cache And Consolidation** - Refresh cache before maintenance and make consolidation rewrites safer.
- [x] **Phase 04: Shared Identity And Access Model** - Extend visibility and access from raw user scope to project-aware shared collaboration. (completed 2026-04-15)
- [ ] **Phase 05: Retrieval And Explainability** - Upgrade recall to hybrid retrieval and make result provenance visible.
- [ ] **Phase 06: Temporal Facts And Conflict Governance** - Model durable memory as evolving facts with lifecycle and conflict states.
- [ ] **Phase 07: Runtime Architecture Upgrade** - Split hot-path admission from background governance and clarify API/worker/MCP roles.

## Phase Details

### Phase 01: Auth Defaults And Tenant Isolation
**Goal:** 关闭认证 fail-open，补齐 API key 的用户绑定，避免共享 `DEFAULT_USER_ID` 导致跨租户混写。
**Depends on:** `.planning/codebase/CONCERNS.md`
**Requirements**: [AUTH-01, AUTH-02]
**Success Criteria** (what must be TRUE):
  1. 服务在缺少有效认证配置时不会以匿名管理员模式启动。
  2. 非管理员 API key 必须绑定具体 `user_id` 才能读写 memory/task。
  3. 认证相关回归测试覆盖默认拒绝与用户绑定边界。
**Plans:** 1 plan

Plans:
- [x] 01-01: Harden auth defaults and bind non-admin API keys to concrete users

### Phase 02: Centralize Memory Governance
**Goal:** 将自动 capture 的长期记忆 / task 判定完全收口到 backend，adapter 只做轻量抑制。
**Depends on:** Phase 01
**Requirements**: [GOV-01]
**Success Criteria** (what must be TRUE):
  1. adapter 不再把本地推断出的 `task_like` / `explicit_long_term` 当成事实写入后端。
  2. backend 成为长期记忆与 task admission 的唯一治理决策点。
  3. 现有 adapter 仍保留轻量去噪和重复抑制，不影响兼容性。
**Plans:** 1 plan

Plans:
- [x] 02-01: Centralize capture governance in backend-owned routing and admission logic

### Phase 03: Stabilize Cache And Consolidation
**Goal:** 让任务规范化与每日整理基于新鲜缓存执行，并把 rewrite/delete 顺序改为安全流程。
**Depends on:** Phase 01
**Requirements**: [CONS-01, CONS-02]
**Success Criteria** (what must be TRUE):
  1. `tasks/normalize` 与 `/consolidate` 在扫描前都会基于后端状态刷新缓存。
  2. canonical rewrite 采用先写新记录、后删旧记录的顺序，避免中途失败丢数据。
  3. 每日整理入口具备基础的单实例锁与重试能力。
**Plans:** 1 plan

Plans:
- [x] 03-01: Refresh cache before maintenance and harden scheduled consolidation execution

### Phase 04: Shared Identity And Access Model
**Goal:** 将 memory/task 的身份与可见性模型从单一 `user_id` 扩展为面向共享协作的 scope/tenant 体系。
**Depends on:** Phase 01
**Requirements**: [IAM-01, IAM-02]
**Success Criteria** (what must be TRUE):
  1. memory 与 task 共用同一套 `project` 级 visibility / enforcement 规则。
  2. 单项目 key 可安全默认落到绑定项目，多项目 key 必须显式声明项目范围。
  3. 结构上为后续 `team/org` 扩展保留清晰入口，而不破坏现有 adapter 兼容性。
**Plans:** 1/1 plans complete

Plans:
- [x] 04-01: Establish shared identity semantics, project-scoped enforcement, and migration-safe compatibility

### Phase 05: Retrieval And Explainability
**Goal:** 将检索升级为 hybrid retrieval，并让每条召回结果可解释、可调试、可审计。
**Depends on:** Phase 02
**Requirements**: [RET-01, RET-02]
**Success Criteria** (what must be TRUE):
  1. recall 组合 semantic、lexical/FTS 与 metadata filters，而不是单一路径。
  2. task/project/name/alias 等高价值查询的命中率比纯向量路径更稳定。
  3. 每条结果都暴露结构化 explainability 字段，便于 API、MCP 和运维调试使用。
**Plans:** 1 plan

Plans:
- [ ] 05-01: Add hybrid retrieval, result provenance, and explainable recall surfaces

### Phase 06: Temporal Facts And Conflict Governance
**Goal:** 将长期记忆从“文本集合”升级为“可演化事实”，支持版本化、冲突检测与 supersede 流程。
**Depends on:** Phase 04
**Requirements**: [FACT-01, FACT-02]
**Success Criteria** (what must be TRUE):
  1. 长期记忆可表达事实的生效、失效、替代与历史版本关系。
  2. 针对同一事实位点的矛盾输入会被检测并进入显式治理状态，而不是静默共存。
  3. 后台整理链路可关闭旧事实并维护事实链，而不只是文本 dedupe。
**Plans:** 1 plan

Plans:
- [ ] 06-01: Introduce fact lifecycle metadata, conflict detection, and supersede governance

### Phase 07: Runtime Architecture Upgrade
**Goal:** 将治理链路拆分为 hot path / background path，并收口到 API + worker + MCP 的生产架构。
**Depends on:** Phase 03
**Requirements**: [OPS-01, OPS-02]
**Success Criteria** (what must be TRUE):
  1. admission / route 保持轻量，重治理逻辑从同步链路中抽离。
  2. background worker 具备清晰的任务边界、幂等约束和失败恢复策略。
  3. 对外运行形态可被明确描述为 API + governance worker + MCP/distribution control plane。
**Plans:** 1 plan

Plans:
- [ ] 07-01: Split runtime responsibilities between hot-path API, background governance worker, and MCP adapters

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Auth Defaults And Tenant Isolation | 1/1 | Complete | 2026-04-16 |
| 2. Centralize Memory Governance | 1/1 | Complete | 2026-04-16 |
| 3. Stabilize Cache And Consolidation | 1/1 | Complete | 2026-04-16 |
| 4. Shared Identity And Access Model | 0/1 | In progress | - |
| 5. Retrieval And Explainability | 0/1 | Not started | - |
| 6. Temporal Facts And Conflict Governance | 0/1 | Not started | - |
| 7. Runtime Architecture Upgrade | 0/1 | Not started | - |
