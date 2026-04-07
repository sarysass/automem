# 命名规范

为避免历史命名混乱，`automem` 采用以下统一规则。

## 产品主命名

所有用户可见、仓库级、文档级名称统一使用：

- `automem`

适用范围：

- 仓库名
- README 标题
- systemd 服务名
- adapter 名称
- 文档标题

## 技术实现命名

实现细节中的底层依赖名只应保留在真正必要的位置，例如：

- `pyproject.toml`
- 后端运行时代码中的 import
- 锁文件

这些名称只表示技术组件，不应出现在产品名、目录名、文档标题或用户可见入口中。

## 目录命名

统一使用：

- `adapters/`：客户端接入模板
- `backend/`：服务端
- `frontend/`：管理前端
- `ops/`：运维模板

不再使用旧目录名：

- `integrations/`

## 环境变量命名

与核心服务连接相关：

- `MEMORY_URL`
- `MEMORY_API_KEY`
- `MEMORY_USER_ID`
- `MEMORY_AGENT_ID`
- `MEMORY_PROJECT_ID`

与本地仓库或 CLI 定位相关：

- `AUTOMEM_HOME`
- `AUTOMEM_CLI`
- `AUTOMEM_PYTHON`
- `AUTOMEM_ENV_FILE`

## 禁止残留

仓库内不应继续保留历史产品级命名、旧项目目录名或旧服务名。
