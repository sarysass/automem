# 贡献指南

欢迎贡献这个项目。

## 基本原则

1. 默认保持开源友好
- 不提交真实密钥
- 不提交个人身份信息
- 不提交真实生产地址

2. 优先补测试
- 新功能优先补测试
- 修 bug 时尽量先补回归测试

3. 保持中文文档优先
- README、集成说明、管理界面文案优先中文
- 如需英文说明，可作为补充而不是替代

## 本地开发

```bash
uv sync --all-groups
uv run pytest
```

## 提交前检查

至少完成：

```bash
uv run pytest
uv run python -m py_compile backend/main.py cli/memory scripts/scheduled_consolidate.py
```

## 配置约束

- 仓库中只保留 `.env.example`
- 真正部署使用的 `.env` 不进入 git

## 运行时接入约束

- runtime 专用适配器不进入本仓库
- 本仓库只维护通用 API / CLI / 数据模型 / 文档
- 各 Agent 的本地实现应放在其自身目录中
