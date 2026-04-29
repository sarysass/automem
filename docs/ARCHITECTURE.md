# 架构说明

`automem` 是一个围绕共享记忆构建的 monorepo，当前运行时收口为三层：

- Hot-path API
- Background governance worker
- MCP / adapter control plane

## 1. Hot-path API

目录：

- `backend/`

职责：

- 提供同步记忆写入、检索、删除接口
- 提供 `memory-route`、`task-resolution`、`task-summaries`
- 维护长期记忆、任务记忆、任务注册表与审计日志
- 暴露健康检查、指标、运行时拓扑与治理作业提交接口

Hot path 的原则是“只做准入、路由、检索和轻量治理判断”。
像 consolidation、历史重写、批量 canonicalize、事实链修复这类重治理动作，不再要求 adapter 或定时脚本直接在请求链路里完成。

## 2. Background Governance Worker

目录：

- `scripts/governance_worker.py`
- `scripts/scheduled_consolidate.py`

职责：

- 消费 API 提交的 `governance_jobs`
- 执行 consolidation 等后台治理作业
- 通过 lease + retry 机制处理 worker 崩溃与失败恢复
- 保持 cron 入口只负责投递作业，而不是直接持有完整治理逻辑

当前支持的后台作业类型：

- `consolidate`

推荐部署形态：

- `automem-consolidate.timer` 负责周期性 enqueue 作业
- `automem-governance-worker.service` 作为常驻 worker 消费治理队列
- 两者日志统一进入 `journalctl`

## 3. 管理与运维层

目录：

- `cli/`
- `frontend/`
- `ops/`
- `scripts/`

职责：

- CLI 优先的管理入口
- 中文管理界面
- systemd 模板、worker 进程与定时整理
- 环境装载、部署与运维脚本

## 4. 客户端接入层

目录：

- `adapters/codex/`
- `adapters/openclaw/`
- `adapters/opencode/`
- `adapters/claude-code/`

职责：

- 将不同 Agent 的插件、hooks、MCP 或工具接口接到统一后端
- 复用统一的记忆数据模型与路由语义
- 保持为“可发布模板”，不内嵌真实环境

这层现在更明确地定位为控制面与分发面：

- 负责 recall / capture / tool exposure
- 调用 hot-path API 获取同步结果
- 不在本地实现额外的 cleanup、consolidation 或治理分支

## 统一契约

无论是哪种客户端接入形态，都共享：

- 同一套 HTTP API
- 同一套 CLI 语义
- 同一套长期记忆 / 任务记忆结构
- 同一套任务治理与 consolidation 语义

其中新的运行时边界是：

- API 负责同步准入与治理作业提交
- Worker 负责后台执行重治理任务
- MCP / adapters 负责把这些能力暴露到不同 Agent 运行时

## 部署建议

- 仓库部署到统一目录，例如 `/opt/automem`
- `backend/.env` 保存服务端环境变量
- `frontend/dist` 作为静态管理界面产物
- 各 Agent 的本地 adapter 通过安装脚本复制到各自运行目录
- 单独运行 `scripts/governance_worker.py` 作为后台治理 worker
- 让 `scripts/scheduled_consolidate.py` 只负责周期性 enqueue consolidate 作业

## 开源边界

仓库内保留：

- 通用源码
- 中文文档
- 示例配置
- adapter 模板

仓库内不保留：

- 真实密钥
- 真实主机地址
- 个人路径
- 个人机器上的安装态副本
