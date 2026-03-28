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

实现细节中允许出现底层依赖名，例如：

- `mem0`
- `qdrant`
- `ollama`

但这些名称只表示技术组件，不应替代产品主命名。

示例：

- 可以写“基于 `mem0` 的后端实现”
- 不应再把整个项目叫做 `memory-platform` 或 `memory-hub`

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

仓库内不应继续出现以下旧产品级命名：

- `memory-hub`
- `memory-platform`
- `Memory Hub`

如需保留历史信息，应仅在迁移说明中以“旧名”身份出现，并明确已废弃。
