# Codex adapter

这是 `automem` 面向 Codex 的公开 MCP adapter 模板。

## 包含内容

- `config.py`：读取本地 `.env`
- `client.py`：封装 `automem` 后端 API
- `mcp_server.py`：暴露共享记忆相关 MCP tools
- `.env.example`：示例配置

## 依赖

```bash
uv sync --all-groups
```

其中 `mcp` 已放在开发依赖组中。

## 配置

复制一份配置：

```bash
cp adapters/codex/.env.example adapters/codex/.env
```

然后填写：

- `MEMORY_URL`
- `MEMORY_API_KEY`
- `MEMORY_USER_ID`
- `MEMORY_AGENT_ID`
- `MEMORY_PROJECT_ID`

## 启动方式

在 adapter 目录内直接运行：

```bash
cd adapters/codex
python mcp_server.py
```

如果你的 Codex 运行环境支持通过文件路径注册 MCP server，也可以把本目录作为模板复制到 `~/.codex/...` 后再接入。

## 暴露的工具

- `memory_health`
- `memory_search`
- `memory_store`
- `memory_route`
- `memory_capture`
- `memory_list`
- `memory_get`
- `memory_forget`
- `task_resolve`
- `task_summary_store`
- `task_list`
- `task_get`
- `task_close`
- `task_archive`
- `memory_metrics`
- `memory_consolidate`

## 说明

- 该模板只包含通用逻辑，不带真实地址、真实 key 或个人配置
- 如需与本地工作流深度集成，请在复制后的本地副本中继续调整
