# Cocon — 多智能体协作引擎

基于 LangGraph 的多 Agent 协作工作流引擎。将自然语言需求拆解为子任务 DAG，由 Planner / Executor / Reviewer / Aggregator 四个专职 Agent 分工执行，支持并行、重试、质量审查和动态重规划。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DeepSeek API Key 和飞书应用凭证

# 3. 启动服务
uvicorn main:app --reload --port 8000
```

## 核心能力

- **任务自动拆解** — 自然语言 → 有依赖关系的子任务 DAG
- **多 Agent 分工** — Planner 规划 → Executor 执行 → Reviewer 审查 → Aggregator 汇总
- **并行执行** — 无依赖的子任务 `asyncio.gather` 并发
- **质量兜底** — Reviewer 逐项打分（完整性/准确性/格式/安全性），不合格自动重试（最多 2 次）
- **动态重规划** — 执行失败时 Replan Agent 评估 DAG 并调整计划
- **MCP 协议** — 通过 MCP 标准接入外部工具（已集成 GitHub Trending）

## 架构概览

```
用户输入 → plan → execute_one → reviewer → continue → aggregate → 最终回答
              ↑        ↑            │            │
              │   retry loop    retry/human   replan/execute
              └────────────────────────────────┘
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/task/submit` | 提交任务，返回 thread_id |
| `GET` | `/v1/task/{id}/status` | 查询任务状态 |
| `GET` | `/v1/planner` | 快速查询 |
| `GET` | `/v1/planner/debug` | 调试（返回完整内部状态） |

## 飞书机器人

@机器人发送消息，自动执行 Cocon pipeline 并以 Markdown 卡片回复。

```bash
# .env 配置
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

## 工具

| 工具 | 来源 | 说明 |
|------|------|------|
| `web_search` | DuckDuckGo (ddgs) | 免费联网搜索 |
| `get_date` | Python datetime | 当前北京时间 |
| `github_trending` | MCP Server | GitHub Trending 热门项目 |

## 项目结构

```
cocon/
├── main.py                      # FastAPI 入口
├── agents/
│   ├── base.py                  # BaseAgent 基类
│   └── prompts.py               # 所有 Agent 的 System Prompt
├── api/
│   ├── tasks.py                 # 任务提交/查询/审批 API
│   └── feishu.py                # 飞书 WebSocket 机器人
├── orchestrator/
│   ├── graph.py                 # LangGraph 编排图（8 个节点）
│   ├── state.py                 # 状态模型
│   └── nodes/
│       ├── planner.py           # PlannerAgent
│       ├── executor.py          # ExecutorAgent
│       ├── reviewer.py          # ReviewerAgent
│       ├── aggregator.py        # AggregatorAgent
│       └── replan.py            # ReplanAgent
├── tools/
│   ├── registry.py              # ToolRegistry 工具注册中心
│   ├── mcp/                     # MCP 客户端 + 进程管理器
│   └── builtin/                 # 内置工具（web_search, get_date）
├── tests/                       # 单元测试
├── docs/                        # 文档
└── mcp_config.json              # MCP Server 配置
```

## 技术栈

| 组件 | 方案 |
|------|------|
| 编排框架 | LangGraph 1.1+ |
| LLM | DeepSeek (v4-pro / v4-flash) |
| Web 框架 | FastAPI |
| 搜索 | DuckDuckGo (ddgs) |
| 飞书 | lark-oapi SDK + WebSocket |
