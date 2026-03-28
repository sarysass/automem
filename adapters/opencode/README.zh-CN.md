# OpenCode adapter

这是 `automem` 面向 OpenCode 的公开 plugin 模板，采用“插件 + CLI”方式接入。

## 能力

- 在新消息进入时自动 recall
- 在会话空闲时自动 capture
- 提供显式工具：
  - `memory_recall`
  - `memory_capture`
  - `memory_tasks`
- 通过 `shell.env` 注入 `MEMORY_*` 与 `AUTOMEM_CLI`

## 目录

- `automem.plugin.ts`
- `package.json`
- `opencode.jsonc.example`

## 前置条件

1. 已安装 OpenCode
2. 已安装本项目依赖
3. 已准备好 automem 服务的环境变量

```bash
export MEMORY_URL="http://127.0.0.1:8888"
export MEMORY_API_KEY="change-me-agent-key"
export MEMORY_USER_ID="example-user"
export MEMORY_AGENT_ID="opencode"
export MEMORY_PROJECT_ID="project-alpha"
export AUTOMEM_CLI="/absolute/path/to/automem/cli/memory"
```

如果不设置 `AUTOMEM_CLI`，插件会优先尝试从仓库相对路径解析 `../../cli/memory`。

## 安装方式

### 项目级安装

```bash
mkdir -p .opencode/plugins .opencode
cp adapters/opencode/automem.plugin.ts .opencode/plugins/
cp adapters/opencode/package.json .opencode/package.json
cp adapters/opencode/opencode.jsonc.example .opencode/opencode.jsonc
```

### 全局安装

```bash
mkdir -p ~/.config/opencode/plugins/automem
cp adapters/opencode/automem.plugin.ts ~/.config/opencode/plugins/automem/
cp adapters/opencode/package.json ~/.config/opencode/plugins/automem/
```

## 校验命令

在本目录执行：

```bash
npm install
npm run typecheck
npm run smoke
```

## 说明

- 这是公开模板，不包含真实部署地址、私有路径或个人身份信息
- 如需更强的策略控制，可以在本地安装副本里继续扩展 recall / capture 逻辑
