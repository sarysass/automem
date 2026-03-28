# 集成边界说明

本文档说明 `automem` 与各类 Agent / runtime 的边界约定。

## 核心原则

`automem` 仓库只负责通用核心能力：

- 后端 API
- CLI
- 前端管理界面
- 任务治理与 consolidation
- 通用测试与文档

运行时专用适配器不放在本仓库中。

## 为什么这样做

这样可以避免把下列内容混进开源仓库：

- 本地插件实现
- MCP 进程入口
- 私有路径
- 用户本地配置
- 只适用于某个 Agent 的运行时代码

这样也更符合发布后的维护边界：

- 核心仓库负责稳定 API 和数据语义
- 各 Agent 本地目录负责接入实现和本地部署

## 推荐接入方式

### Codex

- 使用本地 MCP server
- MCP 实现放在 `~/.codex/...` 之类的 Agent 本地目录
- 通过 `MEMORY_URL`、`MEMORY_API_KEY`、`AUTOMEM_HOME` 等环境变量接入

### OpenClaw

- 使用本地 plugin / hooks
- 插件实现放在 `~/.openclaw/extensions/...`
- 通过本地 `openclaw.json` 或环境变量注入共享记忆配置

### Claude Code

- 使用本地 plugin / hooks / command
- 插件实现放在 `~/.claude/...`
- 通过环境变量连接到共享后端或 CLI

### OpenCode

- 使用本地 plugin / command
- 插件实现放在 `~/.config/opencode/...`
- 建议显式设置 `AUTOMEM_HOME` 或 `MEMORY_PLATFORM_CLI`

## 仓库内应保留什么

适合留在本仓库中的只有：

- 通用 `.env.example`
- API 文档
- 数据模型与治理逻辑
- 示例命令
- 不含私人信息的 benchmark / test fixtures

## 仓库内不应保留什么

- 真实 `.env`
- 私有主机地址
- 个人身份信息
- 实际生产数据导出
- 已安装到本机 Agent 目录中的插件副本

## 适配器开发建议

如果需要为某个 runtime 新增接入，建议做法是：

1. 先在本仓库定义清楚所需 API / CLI 契约。
2. 在对应 Agent 的本地目录实现适配器。
3. 只把通用说明、协议说明、模板配置留在本仓库。

不要把用户本地安装态直接反向塞回核心仓库。
