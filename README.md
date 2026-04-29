# automem

面向多 Agent 协作的共享记忆系统 monorepo。

`automem` 现在同时包含三层内容：

- 服务端核心：FastAPI hot-path API、检索与治理逻辑、任务注册与审计
- 后台治理层：worker 队列、consolidation 作业、失败重试与恢复
- 管理与运维层：CLI 优先入口、中文前端管理界面、运维脚本与 systemd 模板
- 客户端接入层：Codex、OpenClaw、OpenCode、Claude Code 的公开 adapter 模板

## 仓库定位

本仓库是一个可公开发布的完整项目仓库，而不是只包含服务端核心的子集。它包含：

- 通用后端实现
- 通用前端与运维入口
- 可发布的 runtime adapter 源码与模板
- 中文优先的说明文档与示例配置

同时仍然遵守开源边界：

- 不提交真实部署地址、真实密钥、真实主机名
- 不提交个人身份信息、个人路径、私有环境配置
- adapter 只提供可复用模板，不直接携带某台机器的安装态

## 目录结构

```text
automem/
├── adapters/                # Codex / OpenClaw / OpenCode / Claude Code adapters
├── backend/                 # FastAPI 后端
├── cli/                     # 统一 CLI 入口
├── docs/                    # 架构与集成文档
├── frontend/                # 中文前端管理界面
├── ops/                     # 调度与运维模板
├── scripts/                 # 运维脚本
└── tests/                   # 后端与仓库级测试
```

## 快速开始

```bash
uv sync --all-groups
cp backend/.env.example backend/.env
uv run pytest
```

如需本地查看管理界面：

```bash
cd frontend
npm install
npm run dev
```

## 常用命令

```bash
uv run cli/memory --pretty health
uv run cli/memory --pretty search --query "memory-route" --user-id example-user
uv run cli/memory --pretty route --message "请记住：Example Corp 是我的公司" --user-id example-user --agent-id codex --explicit-long-term
uv run cli/memory --pretty capture --message "继续推进共享记忆迁移" --assistant-output "已完成后端重构，下一步验证适配器" --user-id example-user --agent-id codex --project-id project-alpha --task-like
uv run cli/memory --pretty task list --user-id example-user --project-id project-alpha
uv run cli/memory --pretty agent-key create --agent-id openclaw-instance --label "OpenClaw 实例"
uv run cli/memory --pretty cache rebuild --user-id example-user
uv run cli/memory --pretty metrics
uv run cli/memory --pretty consolidate --dry-run
python scripts/scheduled_consolidate.py
python scripts/governance_worker.py
```

其中：

- `scripts/scheduled_consolidate.py` 默认只负责 enqueue consolidate 作业
- `scripts/governance_worker.py` 负责消费后台治理队列
- `GET /v1/runtime-topology` 可查看 API / worker / MCP 的职责划分

推荐在线上同时启用：

- `automem-api.service`
- `automem-governance-worker.service`
- `automem-consolidate.timer`

常用日志查看：

```bash
journalctl -u automem-api -f
journalctl -u automem-governance-worker -f
journalctl -u automem-consolidate.service -n 100
```

## Adapter 概览

- `adapters/codex/`：基于 MCP 的 Codex adapter 模板
- `adapters/openclaw/`：OpenClaw memory plugin 模板
- `adapters/opencode/`：OpenCode plugin + CLI 集成模板
- `adapters/claude-code/`：Claude Code hooks / plugin 模板

这些目录中的文件都保持为可发布、可复制、可二次定制的通用模板。实际部署时，请将模板复制到对应 Agent 的本地目录，并通过环境变量或配置文件注入真实连接信息。

详见：

- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)
- [adapters/README.zh-CN.md](adapters/README.zh-CN.md)
- [docs/INSTALLATION.md](docs/INSTALLATION.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/NAMING.md](docs/NAMING.md)

## 文档

- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)
- [adapters/README.zh-CN.md](adapters/README.zh-CN.md)
- [docs/INSTALLATION.md](docs/INSTALLATION.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/NAMING.md](docs/NAMING.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 许可证

本项目当前使用 MIT 许可证，见 [LICENSE](LICENSE)。
