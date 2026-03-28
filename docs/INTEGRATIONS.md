# 集成架构说明

本文档说明 `automem` 的服务端、客户端 adapter，以及公开仓库边界。

## 完整架构

`automem` 由两大部分组成：

1. 服务端与管理层
- `backend/`
- `cli/`
- `frontend/`
- `ops/`
- `scripts/`

2. 客户端接入层
- `adapters/codex/`
- `adapters/openclaw/`
- `adapters/opencode/`
- `adapters/claude-code/`

服务端负责统一存储、检索、任务治理和管理接口。客户端 adapter 负责把不同 Agent 的上下文、工具、hooks 或 MCP 能力接到同一套核心 API / CLI 上。

## 仓库包含什么

本仓库现在包含：

- 通用后端实现
- 中文管理界面
- CLI 与运维脚本
- 可公开发布的 adapter 模板
- 示例配置与中文文档

## 仓库不包含什么

本仓库不应包含：

- 真实 `.env`
- 真实 API key
- 真实主机地址
- 用户本机路径
- 某个 Agent 已安装完成后的私有副本

也就是说，仓库里放的是“可发布模板”，而不是“某个人机器上的最终安装态”。

## 统一契约

所有 adapter 共享同一套核心契约：

- HTTP API
- CLI 行为
- 路由语义
- 长期记忆 / 任务记忆数据结构
- 任务注册与 task summary 写入方式

推荐优先使用以下环境变量：

- `MEMORY_URL`
- `MEMORY_API_KEY`
- `MEMORY_USER_ID`
- `MEMORY_AGENT_ID`
- `MEMORY_PROJECT_ID`
- `AUTOMEM_HOME`
- `AUTOMEM_CLI`
- `AUTOMEM_PYTHON`

其中：

- `MEMORY_*` 用于连接后端服务与声明身份
- `AUTOMEM_*` 用于帮助 adapter 定位本地仓库或 CLI

## 各 Adapter 推荐形态

### Codex

- 形态：本地 MCP server
- 仓库模板：`adapters/codex/`
- 部署方式：复制到 `~/.codex/...` 或任意本地目录后注册

### OpenClaw

- 形态：memory plugin
- 仓库模板：`adapters/openclaw/`
- 部署方式：复制到 `~/.openclaw/extensions/...` 并在本地配置中启用

### OpenCode

- 形态：plugin + CLI
- 仓库模板：`adapters/opencode/`
- 部署方式：复制到 `.opencode/` 或 `~/.config/opencode/plugins/...`

### Claude Code

- 形态：plugin + hooks
- 仓库模板：`adapters/claude-code/`
- 部署方式：复制到 `~/.claude/plugins/...` 或通过 `--plugin-dir` 加载

## 发布与维护原则

新增 adapter 时请遵守：

1. 先定义清楚与核心服务的通用契约。
2. 仓库内只保留通用源码、模板与示例。
3. 任何面向某台设备的真实配置都只留在本地安装目录，不回写到公开仓库。
4. 产品名统一使用 `automem`，实现依赖名如 `mem0` 只保留在技术细节中。
