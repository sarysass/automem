# automem

面向多 Agent 协作的共享记忆平台。

`automem` 提供一套可发布、可复用的通用核心能力：

- FastAPI 后端
- CLI 优先的运维与管理入口
- 中文管理界面
- 长期记忆 / 任务记忆分层模型
- 路由、任务治理、检索与 consolidation

## 仓库边界

本仓库只保留适合公开发布的通用核心，不再内置任何面向特定运行时的本地插件、MCP 服务或私有部署配置。

这意味着：

- OpenClaw / Codex / Claude Code / OpenCode 的运行时接入代码不放在本仓库
- 真实部署地址、真实密钥、个人身份信息、私有主机名不进入本仓库
- 仓库中的示例、样例数据、基准用例都使用通用占位内容

运行时适配器应部署在各自 Agent 的本地目录中，通过环境变量或 API 配置连接到本仓库提供的核心服务。

## 目录结构

```text
automem/
├── backend/                 # FastAPI 后端
├── cli/                     # 统一 CLI 入口
├── frontend/                # 中文前端管理界面
├── docs/                    # 通用文档
├── ops/                     # 调度与运维模板
├── scripts/                 # 运维脚本
└── tests/                   # 测试
```

## 快速开始

```bash
uv sync --all-groups
cp backend/.env.example backend/.env
uv run pytest
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
```

## 运行时接入原则

本仓库不直接承载运行时适配器源码，但要求所有适配器共享同一套：

- 后端 API
- 路由语义
- 任务注册模型
- 长期记忆与任务记忆的数据结构

详见：[docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)

## 文档

- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

## 许可证

本项目当前使用 MIT 许可证，见 [LICENSE](LICENSE)。
