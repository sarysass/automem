# 安全说明

## 报告方式

如果你发现安全问题，请不要直接公开提交敏感细节。

建议最少提供：

- 影响范围
- 复现步骤
- 触发条件
- 是否涉及密钥、身份验证、路由错误、越权写入、数据泄露

## 当前安全边界

本项目当前主要依赖以下机制：

- `X-API-Key`
- per-agent API key
- 服务端 agent identity 校验
- 审计日志

## 不应提交到仓库的内容

- 真实 API key
- 真实用户 ID
- 真实部署地址
- 真实主机名
- 任何生产环境 `.env`

## 高风险区域

在 review 中应重点关注：

- `memory-route`
- `task-resolution`
- `task lifecycle`
- API key 校验
- search / cache / rerank
- OpenClaw / Codex / Claude / OpenCode 集成层
