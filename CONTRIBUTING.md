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
uv run python -m py_compile backend/main.py cli/memory scripts/scheduled_consolidate.py scripts/install_adapter.py
cd frontend && npm test && npm run build
cd adapters/openclaw && npm install && npm run typecheck && npm run smoke
cd adapters/opencode && npm install && npm run typecheck && npm run smoke
```

## 配置约束

- 仓库中只保留 `.env.example`
- 真正部署使用的 `.env` 不进入 git

## Adapter 贡献约束

- runtime adapter 可以进入本仓库，但必须保持为通用模板或示例
- 不要把某台设备上的最终安装态、私有路径、真实配置直接提交进来
- 本仓库维护的是通用 API / CLI / 数据模型 / adapter 模板 / 文档
- 各 Agent 的真实本地部署副本仍应放在其自身目录中
