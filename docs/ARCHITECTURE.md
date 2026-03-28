# 架构说明

`automem` 是一个围绕共享记忆构建的 monorepo，分为三层。

## 1. 服务端核心

目录：

- `backend/`

职责：

- 提供记忆写入、检索、删除接口
- 提供 `memory-route` 与 `task-resolution`
- 维护长期记忆、任务记忆、任务注册表与审计日志
- 暴露健康检查、指标、管理接口

## 2. 管理与运维层

目录：

- `cli/`
- `frontend/`
- `ops/`
- `scripts/`

职责：

- CLI 优先的管理入口
- 中文管理界面
- systemd 模板与定时整理
- 环境装载、部署与运维脚本

## 3. 客户端接入层

目录：

- `adapters/codex/`
- `adapters/openclaw/`
- `adapters/opencode/`
- `adapters/claude-code/`

职责：

- 将不同 Agent 的插件、hooks、MCP 或工具接口接到统一后端
- 复用统一的记忆数据模型与路由语义
- 保持为“可发布模板”，不内嵌真实环境

## 统一契约

无论是哪种客户端接入形态，都共享：

- 同一套 HTTP API
- 同一套 CLI 语义
- 同一套长期记忆 / 任务记忆结构
- 同一套任务治理与 consolidation 语义

## 部署建议

- 仓库部署到统一目录，例如 `/opt/automem`
- `backend/.env` 保存服务端环境变量
- `frontend/dist` 作为静态管理界面产物
- 各 Agent 的本地 adapter 通过安装脚本复制到各自运行目录

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
