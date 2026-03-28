# 安装与引导

本文档说明如何安装 `automem` 本体，以及如何把 adapter 模板引导到各个 Agent 的本地目录。

## 1. 安装服务端

```bash
uv sync --all-groups
cp backend/.env.example backend/.env
uv run pytest
```

前端管理界面：

```bash
cd frontend
npm install
npm run build
```

## 2. 使用统一安装脚本部署 adapter

仓库内提供：

```bash
python scripts/install_adapter.py <adapter> [--target <dir>] [--force] [--copy-env-example]
```

支持的 adapter：

- `codex`
- `openclaw`
- `opencode`
- `claude-code`

### 示例

安装 Codex adapter 到推荐目录：

```bash
python scripts/install_adapter.py codex --force --copy-env-example
```

安装 OpenClaw adapter 到自定义目录：

```bash
python scripts/install_adapter.py openclaw --target ~/.openclaw/extensions/automem-memory --force
```

安装 OpenCode adapter：

```bash
python scripts/install_adapter.py opencode --force
```

安装 Claude Code adapter：

```bash
python scripts/install_adapter.py claude-code --force --copy-env-example
```

## 3. Adapter 安装后的下一步

安装脚本只复制模板，不会自动写入真实凭据。复制完成后，请在目标目录中完成：

- 填写 `.env` 或本地配置
- 指向真实 `MEMORY_URL`
- 注入真实 `MEMORY_API_KEY`
- 设置本机的 `MEMORY_AGENT_ID`
- 在对应 Agent 内启用该插件或 adapter

## 4. 推荐校验

服务端校验：

```bash
uv run ruff check
uv run pytest
```

前端校验：

```bash
cd frontend
npm test
npm run build
```

Adapter 校验：

```bash
cd adapters/openclaw && npm install && npm run typecheck && npm run smoke
cd adapters/opencode && npm install && npm run typecheck && npm run smoke
```
