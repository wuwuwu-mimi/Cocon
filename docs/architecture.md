# Cocon 架构文档

## 一、调用链总览

```
用户输入（HTTP API / 飞书 @机器人）
    │
    ▼
LangGraph Orchestrator (graph.py)
    │
    ├── plan_node          → PlannerAgent.plan()
    │     └── structured_invoke() → DeepSeek v4-pro → subtask_map
    │
    ├── execute_one_node   → ExecutorAgent.execute()
    │     ├── _resolve_placeholders()  → 替换 {{sub_x.output}}
    │     ├── _run_tool()  → registry.call() → 工具/MCP
    │     └── _run_llm()   → self.invoke() → LLM 直接回答
    │
    ├── reviewer_node      → ReviewerAgent.review()
    │     └── _llm_review() → structured_invoke() → 打分
    │          ├── pass   → continue → [pending? → execute_one : aggregate]
    │          ├── retry  → execute_one（最多 2 次）
    │          └── human  → human_approval → done_with_issues
    │
    ├── continue_node      → 检查是否还有 pending 子任务
    │     └── should_continue → execute / replan / aggregate
    │
    ├── replan_node        → ReplanAgent.evaluate()
    │     └── 调整/跳过/新增子任务 → continue
    │
    └── aggregator_node    → AggregatorAgent.aggregate()
          └── _build_summary() → invoke() → final_output → END
```

## 二、LangGraph 图结构

### 节点清单（8 个）

| 节点 | 函数 | 职责 |
|------|------|------|
| `plan` | `plan_node` | 用户查询 → 子任务 DAG |
| `execute_one` | `execute_one_node` | 找到所有依赖就绪的任务，`asyncio.gather` 并行执行 |
| `reviewer` | `reviewer_node` | 逐项审查执行结果，决定 pass / retry / human |
| `review_next` | `review_next_node` | 切换到批次中下一个待审查任务 |
| `human_approval` | `human_approval_node` | 自动通过有问题的任务，标记为 `done_with_issues` |
| `continue` | `continue_node` | 判断下一步：执行 / 重规划 / 汇总 |
| `replan` | `replan_node` | 评估 DAG 状态，跳过/替换/调整依赖或新增子任务 |
| `aggregate` | `aggregator_node` | 整合所有结果，生成最终回答 |

### 条件路由

- **review_route**: `pass` → continue / `retry` → execute_one / `human` → human_approval / 同批次还有待审 → review_next
- **should_continue**: 有 pending → execute_one / 有 blocked/failed → replan / 全部完成 → aggregate

## 三、Agent 详解

### BaseAgent (`agents/base.py`)

**文件位置**: `agents/base.py:11`

所有 Agent 的基类。负责 LLM 客户端初始化和通用调用逻辑。

**核心方法**:

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `invoke()` | `user_message, context` | `str` | 发送 SystemMessage + HumanMessage，返回文本 |
| `structured_invoke()` | `user_message, output_schema, context` | `dict` | 在 prompt 末尾追加 JSON 格式要求，解析返回的 JSON。内置 `_repair_json()` 修复常见错误（尾逗号、Markdown 包裹、非 JSON 前缀） |

**LLM 配置**:
- 通过 `ChatOpenAI` 兼容 DeepSeek API
- `temperature=0.1`
- 模型由 `model_name` 参数决定（各子类从环境变量注入）

---

### PlannerAgent (`orchestrator/nodes/planner.py`)

**模型**: `PLAN_MODEL`（deepseek-v4-pro）

**System Prompt**: `PLANNER_SYSTEM_PROMPT`（`agents/prompts.py:1`）

**核心方法**:

| 方法 | 说明 |
|------|------|
| `plan(user_query)` | 调用 `structured_invoke()` 传入 output_schema 示例，LLM 返回 `{"subtasks": [...], "parallel_groups": [...]}` |
| `plan_to_subtask_map(plan)` | 将 LLM 原始输出归一化为 `Dict[str, Subtask]`。兼容 `tasks`/`subtasks` 两种 key、list/dict 两种结构、缺失字段 `.get()` 兜底 |

**输出格式**:
```json
{
  "subtasks": [
    {"id": "sub_1", "description": "...", "tool": "web_search", "args": {...}, "depends_on": [], "expected_output": "..."}
  ],
  "parallel_groups": [["sub_1"], ["sub_2"]]
}
```

---

### ExecutorAgent (`orchestrator/nodes/executor.py`)

**模型**: `EXECUTOR_MODEL`（deepseek-v4-flash）

**System Prompt**: `EXECUTOR_SYSTEM_PROMPT`（`agents/prompts.py:34`）

**核心方法**:

| 方法 | 说明 |
|------|------|
| `execute(subtask, context)` | 1. 解析 `{{sub_x.output}}` 占位符 2. tool≠none → `_run_tool()` 3. tool=none → `_run_llm()` |
| `_run_tool(tool_name, args)` | `await registry.call(tool_name, caller_id=self.name, **args)` |
| `_run_llm(subtask, args, context)` | 拼 prompt（任务描述+预期输出+参数+前置结果）→ `self.invoke()` |
| `_resolve_placeholders(args, context)` | 递归替换 args 中的 `{{sub_id.path}}` |
| `_lookup_context(path, context)` | 按点路径从 context 取值，保留 int/float/bool 原始类型 |

**占位符示例**: `{{sub_1.output.data.results}}` → `context["sub_1"]["data"]["results"]`

---

### ReviewerAgent (`orchestrator/nodes/reviewer.py`)

**模型**: `PLAN_MODEL`（deepseek-v4-pro）

**System Prompt**: `REVIEWER_SYSTEM_PROMPT`（`agents/prompts.py:59`）

**核心方法**:

| 方法 | 说明 |
|------|------|
| `review(subtask, result, retry_count)` | 工具失败 → 直接重试/人工；工具成功 → `_llm_review()` 打分 |
| `_llm_review(subtask, result)` | 传入任务类型（tool/LLM）、expected_output、实际输出 → LLM 逐项审查 |

**审查维度和路由**:
```
完整性 / 准确性 / 格式正确性 / 安全性
    │
    ├── score ≥ 0.8 → pass
    ├── 0.5 ≤ score < 0.8 → retry (retry<2) / human (retry≥2)
    └── score < 0.5 → retry (retry<2) / human (retry≥2)
```

**智能重试**: Reviewer 反馈中包含新搜索词时，`graph.py` 自动更新 `subtask.args.query`

---

### AggregatorAgent (`orchestrator/nodes/aggregator.py`)

**模型**: `EXECUTOR_MODEL`（deepseek-v4-flash）

**System Prompt**: `AGGREGATOR_SYSTEM_PROMPT`（`agents/prompts.py:92`）

**核心方法**:

| 方法 | 说明 |
|------|------|
| `aggregate(original_query, subtask_map)` | 构建子任务摘要 → `self.invoke()` → Markdown 最终回答 |
| `_build_summary(subtask_map)` | 遍历所有子任务，按状态打标签（[成功]/[部分成功]/[失败]/[阻塞]），附上结果数据 |

---

### ReplanAgent (`orchestrator/nodes/replan.py`)

**模型**: `PLAN_MODEL`（deepseek-v4-pro）

**System Prompt**: `REPLAN_SYSTEM_PROMPT`（`agents/prompts.py:109`）

**核心方法**:

| 方法 | 说明 |
|------|------|
| `evaluate(original_query, subtask_map)` | 构建状态摘要 → `structured_invoke()` → 返回 {action, adjustments, new_subtasks} |

**可选动作**: `skip`（跳过阻塞任务）/ `replace`（生成替代子任务）/ `adjust_deps`（移除失败依赖）/ `none`（不做调整）

---

## 四、工具系统

### ToolRegistry (`tools/registry.py`)

| 方法 | 说明 |
|------|------|
| `register(name, func, schema, acl)` | 注册工具 |
| `list_tools()` | 返回 OpenAI Function Calling 格式的工具列表 |
| `call(name, caller_id, **kwargs)` | 调用工具，ACL 检查，30s 超时 |

### 内置工具 (`tools/builtin/`)

| 工具 | 文件 | 实现 |
|------|------|------|
| `web_search` | `web_search.py` | DuckDuckGo (ddgs)，内存缓存 50 条，限速 1.5s 间隔，15s 超时，`asyncio.to_thread` 避免阻塞事件循环 |
| `get_date` | `get_date.py` | Python datetime，返回 `{date, date_cn}` |

### MCP 集成 (`tools/mcp/`)

| 文件 | 职责 |
|------|------|
| `client.py` | JSON-RPC 2.0 over stdio，初始化和工具调用 |
| `manager.py` | 进程生命周期管理，启动时自动注册，命名简化 |

**配置文件**: `mcp_config.json`
```json
{
  "mcpServers": {
    "github-trending": {
      "command": "python",
      "args": ["-m", "github_trending_mcp"]
    }
  }
}
```

## 五、状态管理

### Subtask

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | 唯一标识 |
| `description` | `str` | 任务描述 |
| `tool` | `str` | 工具名，`"none"` 表示 LLM 直接处理 |
| `args` | `dict` | 工具参数 |
| `depends_on` | `List[str]` | 依赖的前置任务 ID |
| `expected_output` | `str` | 预期输出（Reviewer 验收标准） |
| `status` | `str` | `pending` / `reviewing` / `done` / `done_with_issues` / `failed` / `blocked` |
| `result` | `Optional[dict]` | `{"ok": True/False, "data": ..., "error": ...}` |
| `retry_count` | `int` | 已重试次数 |
| `review_status` | `str` | `pending` / `pass` / `retry` / `blocked_human` / `auto_approved` |
| `review_score` | `float` | Reviewer 评分 (0.0-1.0) |

### OrchestratorState

| 字段 | 类型 | 用途 |
|------|------|------|
| `original_query` | `str` | 用户原始问题 |
| `subtask_map` | `Dict[str, Subtask]` | 子任务字典 |
| `context` | `Dict[str, dict]` | 累积执行结果 |
| `current_subtask_id` | `str` | 当前处理的子任务 |
| `final_output` | `str` | 最终回答 |
| `status` | `str` | 任务状态 |

## 六、API 端点

所有端点前缀 `/v1`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/task/submit` | 提交任务，返回 `thread_id` + 摘要 |
| `GET` | `/task/{id}/status` | 通过 LangGraph checkpoint 查询任务状态 |
| `POST` | `/task/{id}/approve` | 人工审批（`Command(resume=...)`） |
| `GET` | `/planner` | 快速查询（无 thread_id） |
| `GET` | `/planner/debug` | 完整调试信息 |

## 七、飞书接入

**文件**: `api/feishu.py`

通过 lark-oapi SDK WebSocket 长连接接收 `im.message.receive_v1` 事件。

**流程**:
```
飞书群 @机器人 → WebSocket 事件 → on_message()
    → asyncio.run_coroutine_threadsafe(run(), main_loop)
    → graph.ainvoke() → send_markdown_card()
    → 飞书 interactive 卡片（Markdown 渲染）
```

**回复格式**: 飞书 `interactive` 消息 + `markdown` 标签，支持标题/表格/链接/代码块。

## 八、技术栈

| 组件 | 方案 | 用途 |
|------|------|------|
| 编排框架 | LangGraph 1.1+ | DAG 状态图、条件路由、interrupt |
| LLM 客户端 | langchain-openai | 兼容 DeepSeek API |
| Planner/Reviewer/Replan | deepseek-v4-pro | 强推理任务 |
| Executor/Aggregator | deepseek-v4-flash | 执行和汇总（便宜快速） |
| Web 框架 | FastAPI | 原生 async |
| 搜索 | DuckDuckGo (ddgs) | 免费搜索 |
| 飞书 | lark-oapi SDK | WebSocket + 消息发送 |
| MCP | JSON-RPC 2.0 / stdio | 外部工具协议 |
