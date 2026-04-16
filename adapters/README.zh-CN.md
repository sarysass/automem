# automem adapters

这里收录 `automem` 的公开客户端接入模板。

## 当前包含

| Adapter | 目录 | 形态 | 说明 |
| --- | --- | --- | --- |
| Codex | `adapters/codex/` | MCP server | 直接把共享记忆能力暴露为 MCP tools |
| OpenClaw | `adapters/openclaw/` | memory plugin | 自动 recall / capture，并提供显式工具 |
| OpenCode | `adapters/opencode/` | plugin + CLI | 借助 `cli/memory` 接入共享记忆 |
| Claude Code | `adapters/claude-code/` | plugin + hooks | 在会话开始、用户提交和停止时执行 recall / capture |

## 使用原则

- 仓库中的 adapter 是“可发布模板”
- 实际部署时，请复制到对应 Agent 的本地目录
- 真实 `MEMORY_URL`、`MEMORY_API_KEY`、`MEMORY_USER_ID` 等值只在本地配置
- 若需要自定义命名、工具集合或触发策略，请在复制后的本地副本里调整

运行时边界上，请保持：

- adapter 负责 recall / capture / tool exposure
- adapter 只调用后端 hot-path 接口
- 不在 adapter 本地继续长出 consolidation、cleanup 或治理分支
- 后台治理统一交给 API + worker 链路处理

统一安装脚本见：

- `scripts/install_adapter.py`

统一安装说明见：

- [docs/INSTALLATION.md](../docs/INSTALLATION.md)

## 开发约束

- 产品名称统一使用 `automem`
- 不提交真实机器路径、主机名、账号、密钥
- 底层依赖名只保留在必要的实现细节中，不作为产品主命名
