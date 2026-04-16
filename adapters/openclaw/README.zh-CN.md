# OpenClaw adapter

这是 `automem` 面向 OpenClaw 的公开 memory plugin 模板。

## 能力

- 自动 recall：在 agent 启动前查询长期记忆与相关任务记忆
- 自动 capture：在成功结束后调用 `memory-route` 并写入结果
- 显式工具：
  - `memory_search`
  - `memory_store`
  - `memory_list`

## 配置方式

你可以在 OpenClaw 的插件配置中填写：

- `api.baseUrl`
- `api.apiKey`
- `identity.userId`
- `identity.agentId`
- `identity.projectId`

也可以通过环境变量提供：

```bash
export OPENCLAW_AUTOMEM_URL="http://127.0.0.1:8888"
export OPENCLAW_AUTOMEM_API_KEY="change-me-agent-key"
export OPENCLAW_AUTOMEM_USER_ID="example-user"
export OPENCLAW_AUTOMEM_AGENT_ID="openclaw-instance"
export OPENCLAW_AUTOMEM_PROJECT_ID="project-alpha"
```

## 安装建议

优先使用仓库自带安装脚本部署到 OpenClaw 扩展目录：

```bash
python scripts/install_adapter.py openclaw --target ~/.openclaw/extensions/automem-memory --force
```

然后在 OpenClaw 的本地配置中启用该插件。

如果目标目录属于 `root` 或其他系统用户，不要使用会保留源文件 uid/gid 的部署方式（例如跨机器 `cp -a` / `rsync -a`）。OpenClaw 会把属主异常的插件目录判定为 `suspicious ownership` 并直接屏蔽。

## 校验命令

在本目录执行：

```bash
npm install
npm run typecheck
npm run smoke
```

## 说明

- 本模板是公开版，不包含任何真实地址、个人路径或私有配置
- 如需更复杂的 recall / capture 策略，建议在本地安装副本里继续扩展
