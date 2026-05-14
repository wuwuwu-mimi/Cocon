# MCP 工具集成文档

## 概述

Cocon 通过 MCP 协议（Model Context Protocol）接入外部工具，实现了工具系统的水平扩展。开发者只需配置 MCP Server，无需为每个工具手写 Python 封装代码。

## 架构

```
mcp_config.json                ToolRegistry
     │                              │
     ▼                              │
MCPManager.load_all()               │
     │                              │
     ├─ MCPClient.connect()         │
     │   └─ JSON-RPC initialize     │
     ├─ list_tools()                │
     │   └─ 获取工具定义列表         │
     └─ registry.register() ────────┘
          │
          ▼
     Planner prompt 自动包含
     {tools_description}
```

## 文件结构

```
tools/mcp/
├── client.py      # MCPClient: JSON-RPC 2.0 over stdio
└── manager.py     # MCPManager: 进程生命周期 + 命名管理

mcp_config.json    # MCP Server 配置文件
tools/__init__.py  # init_mcp() 启动时调用
main.py            # startup hook → await init_mcp()
```

## MCPClient

**职责**：通过 stdio 与 MCP Server 子进程通信

**核心流程**：
1. `connect()` — 启动子进程 → `initialize` 握手 → `tools/list` 获取工具
2. `call_tool(name, arguments)` — `tools/call` → 解析 `content[]` → 返回 `{ok, data}`
3. `shutdown()` — 关闭 stdin → 等待进程退出

**关键实现**：
- JSON-RPC 请求带递增 `id`，响应对应 `id` 匹配到 `Future`
- `_read_loop` 后台任务持续从 stdout 读取（4096 字节块 → 按 `\n` 分割 → JSON 解析）
- 30 秒超时与 `ToolRegistry.call()` 的 30 秒超时一致
- Windows 下用 `read(4096)` 替代 `readline()` 规避换行符兼容问题

## MCPManager

**职责**：管理多个 MCP Server 的生命周期

**核心功能**：
- `load_all()` — 读取 `mcp_config.json` → 逐个启动 → 注册工具
- **命名简化**：`get_github_trending` → `github_trending`（去掉 `get_` 前缀，让 Planner 更容易理解）
- **Python 路径修正**：配置中 `"command": "python"` 自动替换为 `sys.executable`
- **容错**：某个 Server 启动失败 → 记录日志，继续加载其他 Server
- `atexit` 注册 `cleanup_all()` 防止僵尸进程

## mcp_config.json

```json
{
  "mcpServers": {
    "github-trending": {
      "command": "python",
      "args": ["-m", "github_trending_mcp"],
      "env": {}
    }
  }
}
```

**字段说明**：
| 字段 | 说明 |
|------|------|
| `command` | 启动命令（`python`/`python3` 会自动用 `sys.executable`） |
| `args` | 命令参数列表 |
| `env` | 环境变量（可用于注入 API Key 等敏感信息） |

## 当前集成工具

| 工具名 | 来源 | 描述 |
|--------|------|------|
| `github_trending` | github-trending-mcp (PyPI) | 查询 GitHub trending 项目（支持按语言/时间筛选） |
| `web_search` | DuckDuckGo (内置) | 联网搜索 |
| `get_date` | datetime (内置) | 获取当前北京时间 |

## 新增 MCP Server 步骤

1. 安装 MCP Server（如 `pip install xxx-mcp`）
2. 在 `mcp_config.json` 中添加配置
3. 重启服务

无需修改任何 Python 代码——启动时自动发现工具。

## Planner 中使用 MCP 工具

当用户问"今天 GitHub 上哪些 Python 项目 star 增长快"时：

```
Planner 看到 registry.list_tools():
  - web_search: 联网搜索
  - get_date: 获取当前北京时间
  - github_trending: Get GitHub trending repos

Planner 生成的 subtask:
  sub_1: tool=get_date
  sub_2: tool=github_trending (language=python, since=daily)
```

Executor 调用 `registry.call("github_trending", ...)` → MCPManager → MCPClient → MCP Server → 返回 Markdown 格式的 trending 列表。

## 调试

```bash
# 测试 MCP Server 是否正常
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
  python -m github_trending_mcp

# 查看已注册工具
curl http://127.0.0.1:8000/v1/planner/debug?query=test | jq '.subtasks'
```
