# Claude Code adapter

这是 `automem` 面向 Claude Code 的公开 plugin + hooks 模板。

## 能力

- `SessionStart` 时预加载相关任务与长期记忆
- `UserPromptSubmit` 时按当前 prompt recall
- `Stop` 时自动 capture 当前轮次

## 包含内容

- `.claude-plugin/plugin.json`
- `hooks/hooks.json`
- `scripts/common.py`
- `scripts/recall.py`
- `scripts/capture.py`
- `.env.example`

## 配置

可通过环境变量配置：

```bash
export MEMORY_URL="http://127.0.0.1:8888"
export MEMORY_API_KEY="change-me-agent-key"
export MEMORY_USER_ID="example-user"
export MEMORY_AGENT_ID="claude-code"
export MEMORY_PROJECT_ID="project-alpha"
export AUTOMEM_CLI="/absolute/path/to/automem/cli/memory"
export AUTOMEM_PYTHON="/absolute/path/to/automem/.venv/bin/python"
```

如果不设置 `AUTOMEM_CLI`，脚本会优先尝试从仓库相对路径解析 `cli/memory`。

## 启用方式

可将本目录复制到 Claude Code 的插件目录，或直接通过 `--plugin-dir` 加载：

```bash
claude --plugin-dir /absolute/path/to/automem/adapters/claude-code
```

## 说明

- 本模板不包含任何真实密钥、真实路径或个人环境信息
- 如需调整 recall / capture 时机，可以在本地安装副本中修改 `hooks/hooks.json`
