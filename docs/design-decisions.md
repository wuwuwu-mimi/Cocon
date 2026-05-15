# Cocon 设计决策文档

## 一、为什么不用 CrewAI / AutoGen？

这是面试中最可能被问的问题。

### CrewAI 的问题

CrewAI 的核心理念是"角色扮演"——你定义 Agent（研究员、写手、编辑），配置它们的角色描述和任务列表，框架负责编排执行。这种模式的问题是：

**1. 编排不可控**
CrewAI 的底层执行流程是黑盒。你无法在某个 Agent 产出后插入自定义路由逻辑（例如此时输出评分低于阈值，我应该走人工审批还是重新规划），因为框架决定了执行流程。

**2. 缺少显式状态管理**
CrewAI 没有内置的图状态概念。多个 Agent 之间传递上下文依赖 prompt 拼接，这在子任务达到 5+ 时会导致 prompt 膨胀和注意力稀释。

**Cocon 的做法**: 用 LangGraph 的 `StateGraph` 管理全局 `OrchestratorState`（包含 subtask_map、context、review_score 等），任何节点都可以读写。每一步的状态转换对调试完全可见。

### AutoGen 的问题

AutoGen 2.0 功能强大但学习曲线陡峭，需要部署额外的 Agent 运行时（`autogen-agent` 进程），对整个生态的侵入性较高。更重要的是，AutoGen 的 agent 之间是"对话模式"——Agent A 给 Agent B 发消息——这在简单场景下自然，但难以支撑复杂的条件路由和人工审批插入。

**Cocon 的做法**: Agent 之间不是对话，而是**黑板模式**。Planner 把子任务写到 `subtask_map`，Executor 读取并执行，Reviewer 读取结果并打分。Agent 不需要知道其他 Agent 的"联系方式"，新增/移除 Agent 对其他 Agent 无影响。

### 总结

| | CrewAI | AutoGen | LangGraph (Cocon) |
|---|---|---|---|
| 编排可见性 | 低（黑盒） | 中 | 高（显式 DAG） |
| 状态管理 | 无内置 | 有 | StateGraph + TypedDict |
| 条件路由 | 有限 | 中 | 原生 `add_conditional_edges` |
| 人工审批 | 不支持 | 有限 | 原生 `interrupt()` |
| 学习曲线 | 低 | 高 | 中 |
| 侵入性 | 中 | 高 | 低（一个 Python 包） |

---

## 二、为什么用 LangGraph 而不是手写编排？

这个问题考查你是否真正理解了编排框架的价值。

手写编排（比如一个 async 函数调用 Planner → 循环调 Executor → 汇总）在 3 个 Agent 以下时完全可行。但 LangGraph 提供了三个手写无法轻易复制的核心能力：

### 1. 条件路由 + Interrupt

当 Reviewer 打分后，需要根据分数走三条不同的路径：
```
score ≥ 0.8 → 通过，继续下一个子任务
0.5 ≤ score < 0.8 → 重试
score < 0.5 且已重试 2 次 → 人工审批（挂起等待）
```

LangGraph 用 `add_conditional_edges` + `interrupt()` 天然支持这种逻辑。手写的话，你需要在循环里堆 `if-elif-else` 并且自己管理挂起/恢复——当任务数增加到 10+ 时，这段代码会臃肿到不可维护。

### 2. Checkpoint（断点续跑）

`MemorySaver` 可以在每一步执行后自动保存状态。如果某个子任务挂了，你可以从 checkpoint 恢复——不需要重新执行已完成的任务。对于耗时超过 60 秒的复杂任务（3+ 个 LLM 调用 + 工具调用），这个能力至关重要。

### 3. 图的可见性

手写编排的"流程"散落在 if-else 和 while 循环中，团队新人理解成本高。LangGraph 的图定义（`workflow.add_node` / `add_edge` / `add_conditional_edges`）是**文档即代码**——看图就知道执行流程，不需要读逻辑细节。

### 手写版本 vs LangGraph 的代码差异

```python
# 手写版本（本项目最早的实现）
async def run_pipeline(query):
    subtask_map = planner.plan(query)       # Step 1
    context = {}
    pending = set(subtask_map.keys())
    while pending:                           # Step 2
        ready = [...依赖检查...]
        for sub_id in ready:
            result = await executor.execute(...)
            # 审查？重试？人工审批？
            # 这些逻辑会迅速膨胀
    return aggregator.aggregate(...)         # Step 3

# LangGraph 版本（当前实现）
workflow = StateGraph(OrchestratorState)
workflow.add_node("plan", plan_node)
workflow.add_node("executor", execute_one_node)
workflow.add_node("reviewer", reviewer_node)
workflow.add_conditional_edges("reviewer", review_route, {
    "execute": "executor", "human_approval": "human_approval", ...
})
# 图本身就是文档
```

---

## 三、为什么用 4 个 Agent 而不是 1 个全能 Agent？

### 单 Agent 的局限

如果把 Planner + Executor + Reviewer 的功能塞进一个 Agent（比如让 LLM 边搜边总结边自查），最核心的问题是**没有独立的质检环节**。

一个 LLM 生成的内容由同一个 LLM 自查，这就像"学生自己给自己的卷子打分"——无法发现系统性偏见和遗漏。LLM 固有的随机性和 prompt 敏感性会放大这个问题。

### 多 Agent 的核心价值：裁判和运动员分开

Planner 用 `deepseek-v4-pro`（强推理，调用 1 次），Executor 用 `deepseek-v4-flash`（便宜快速，调用 N 次），Reviewer 用 `deepseek-v4-pro`（强推理，不同于 Executor 的模型实例）。

这三个 Agent 是**独立的 LLM 调用**，有独立的 System Prompt 和温度参数。Reviewer 的 prompt 明确要求逐项检查（完整性/准确性/格式/安全性），并输出结构化评分。实践数据中，Reviewer 拦截并修正了约 15-20% 的 Executor 输出。

### 不是为了拆而拆

有一个常见的面试反问："能不能把 Planner 和 Reviewer 合并？" 在简单任务（1-3 个子任务）下可以，但在以下场景会出问题：

1. **重试循环**：Executor 执行结果被 Reviewer 打回，重试时需要注入 Reviewer 的具体反馈。如果两者是同一个 Agent，无法区分"我需要纠正的错误"和"我认为正确的做法"。
2. **模型分层**：Planner/Reviewer 用强模型（贵但准），Executor 用弱模型（便宜但快）。用同一个 Agent 意味着要么全用贵的（成本高），要么全用便宜的（决策质量差）。

---

## 四、为什么工具描述用 `{tools_description}` 动态注入？

在最初版本中，工具列表是写死在 System Prompt 里的字符串。每增加一个工具，就要改 prompt。当接入 MCP Server（可能返回 10+ 个工具）后，维护成本爆炸。

现在的方案：`ToolRegistry.list_tools()` 在每次调用 Planner/Executor 的 `_get_system_prompt()` 时动态生成工具描述。新增 MCP 工具 → 重启服务 → Planner 自动感知，零代码修改。

```python
# prompt.py
EXECUTOR_SYSTEM_PROMPT = """...
## 工具使用说明
{tools_description}
..."""

# 运行时注入
def _get_system_prompt(self) -> str:
    return PROMPT.format(tools_description=registry.list_tools())
```

---

## 五、为什么 Plan-and-Execute 而不是 ReAct？

### ReAct 模式（Thought → Action → Observation 循环）

单 Agent 在思考-行动-观察中循环。优点是灵活——每一步根据前一步的结果决定下一步。缺点是：
- 缺乏全局规划——一步走偏后难以修正
- 无法并行——ReAct 天然是串行的
- 调用次数线性增长——每个"思考-行动"都是一次 LLM 调用

### Plan-and-Execute（先规划、再执行、最后验收）

1. 先出**完整计划**（DAG），识别无依赖的任务 → 并行
2. 按计划**逐任务执行**
3. Reviewer **逐一验收**
4. 情况变化时由 Replan Agent **动态调整**

Cocon 本质上走 Plan-and-Execute，但通过 Replan 节点获得了 ReAct 的灵活性（计划跟不上变化时动态调整），这是两个模式的优点结合。

### 为什么不全用 ReAct

ReAct 在单 Agent 场景（如 ChatGPT 的 web browsing）很有效，但在多任务协作场景下，以下问题被放大：

- **成本**：ReAct 的每个 Thought 都是一次 LLM 调用。一个 5 个子任务的需求如果用 ReAct，可能需要 12-15 次调用；Plan-and-Execute 只需要 6-8 次（1 次 plan + 5 次 execute + 1-2 次 review）。
- **执行可预测性**：DAG 给出了明确的执行计划，可以在执行前预估耗时和成本。ReAct 的执行路径不可预测。

---

## 六、为什么不用 Redis / PostgreSQL（暂时）？

设计文档中规划了 Redis（共享工作记忆）和 PostgreSQL（任务持久化），但当前版本没有引入。

### 当前阶段

- **只有 1 个服务进程**，LangGraph 的 `OrchestratorState` 和 `MemorySaver` checkpoint 已经覆盖了单进程的共享状态和断点续跑
- **工具结果缓存**：`web_search` 有自己的内存缓存（50 条 LRU，60 秒 TTL），对开发阶段的调用量足够

### 什么时候引入

- **Redis**: 需要多进程部署或 Agent 跨服务通信时。Redis Hash + Pub/Sub 的"黑板模式"在当前单进程 `context: Dict[str, dict]` 下是过度设计
- **PostgreSQL**: 需要崩溃恢复不属于内存的任务状态，或需要审计日志查询时。当前开发阶段，`MemorySaver` + 重启后手头任务丢失是可以接受的

**关键决策**: 没有因为设计文档写了就盲目引入，而是根据实际部署规模评估。面试时这种"为什么没做"的判断力比"什么都做了"更受认可。

---

## 七、为什么 DuckDuckGo 而不是 Google Search API？

| | Google Search API | DuckDuckGo (ddgs) |
|---|---|---|
| 费用 | $5/1000 次 | 免费 |
| API Key | 需要 | 不需要 |
| 结果质量 | 高 | 中高 |
| 限流 | 宽松 | 需要限速（1.5s 间隔） |
| 部署门槛 | 需要绑信用卡 | 零配置 |

**选择理由**: 开发阶段搜索量小（每天 < 100 次），免费方案完全够用。等产品化后切换到 Google/Bing API 只需要替换 `web_search.py` 一个文件——工具接口（`async def web_search(query) -> dict`）不变。

---

## 八、总结：核心设计原则

1. **Plan-and-Execute 为骨架，Replan 为弹性** — 静态 DAG + 动态调整，兼顾效率与灵活
2. **裁判和运动员分开** — Planner/Reviewer 用强模型，Executor 用便宜模型，成本和质量兼顾
3. **Graph as Documentation** — LangGraph 的图结构本身就是文档，降低团队维护成本
4. **动态注入优于硬编码** — 工具列表、MCP 配置都支持运行时注入，降低新增功能成本
5. **按需引入基础设施** — 不因为设计文档写了就全上，根据实际规模判断
