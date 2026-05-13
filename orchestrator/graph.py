"""LangGraph 编排图

图结构:
  __start__
      │
      ▼
    plan ─────────────── 用户查询 → subtask_map
      │
      ▼
  execute_one ───────── 挑一个依赖就绪的子任务执行
      │
      ▼
  reviewer ──────────── 审查执行结果，逐项打分
      │
      ├── pass ──────→ should_continue → execute_one 或 END
      ├── retry ─────→ execute_one（重试，带 reviewer 反馈）
      └── human ─────→ should_continue（阻塞该任务，继续其他）
"""
import logging

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from orchestrator.state import OrchestratorState
from orchestrator.nodes.planner import PlannerAgent
from orchestrator.nodes.executor import ExecutorAgent
from orchestrator.nodes.reviewer import ReviewerAgent
from orchestrator.nodes.aggregator import AggregatorAgent
from orchestrator.nodes.replan import ReplanAgent

logger = logging.getLogger(__name__)

# 模块级单例
_planner = PlannerAgent()
_executor = ExecutorAgent()
_reviewer = ReviewerAgent()
_aggregator = AggregatorAgent()
_replan = ReplanAgent()


MAX_RETRY = 2


# ---------------------------------------------------------------------------
# 节点函数
# ---------------------------------------------------------------------------

async def plan_node(state: OrchestratorState) -> dict:
    """规划节点：用户查询 → 子任务 DAG"""
    query = state["original_query"]
    logger.info("[plan_node] 开始规划: %s", query)

    subtask_map = _planner.plan(query)
    if not subtask_map:
        logger.warning("[plan_node] 规划失败")
        return {"status": "failed", "final_output": "规划失败，未生成子任务"}

    logger.info("[plan_node] 完成: %d 个子任务", len(subtask_map))
    return {
        "subtask_map": subtask_map,
        "context": {},
        "status": "executing",
    }


async def execute_one_node(state: OrchestratorState) -> dict:
    """执行节点：找出所有依赖就绪的子任务，asyncio.gather 并行执行

    同一批次内的任务无相互依赖，并发执行。retry 任务也在此处理。
    """
    import asyncio

    subtask_map = state.get("subtask_map", {})
    context = state.get("context", {})

    pending = {sid for sid, st in subtask_map.items()
               if st.get("status") == "pending"}
    completed = {sid for sid, st in subtask_map.items()
                 if st.get("status") in ("done", "failed", "blocked")}
    all_ids = set(subtask_map.keys())

    # 找出所有依赖已满足的任务
    ready_ids = []
    for sid in pending:
        deps = subtask_map[sid].get("depends_on", [])
        missing = [d for d in deps if d not in all_ids]
        if missing:
            logger.warning("[executor] %s 依赖不存在: %s，标记为 blocked", sid, missing)
            subtask_map[sid]["status"] = "blocked"
            completed.add(sid)
            continue
        if all(dep in completed for dep in deps):
            ready_ids.append(sid)

    if not ready_ids:
        for sid in pending - completed:
            subtask_map[sid]["status"] = "blocked"
            logger.warning("[executor] %s 因依赖无法满足被阻塞", sid)
        remaining = {sid for sid, st in subtask_map.items()
                     if st.get("status") == "pending"}
        if not remaining:
            return {"subtask_map": subtask_map, "status": "done"}
        return {"subtask_map": subtask_map}

    # 单任务直接执行，多任务 asyncio.gather 并行
    if len(ready_ids) == 1:
        sub_id = ready_ids[0]
        subtask = subtask_map[sub_id]
        logger.info("[executor] 执行: %s (tool=%s)", sub_id, subtask.get("tool"))
        result = await _executor.execute(subtask, context)
        context[sub_id] = result
        subtask["status"] = "reviewing"
        subtask["result"] = result
    else:
        logger.info("[executor] 并行执行 %d 个任务: %s", len(ready_ids), ready_ids)

        async def run_one(sub_id: str):
            subtask = subtask_map[sub_id]
            result = await _executor.execute(subtask, context)
            return sub_id, result

        gathered = await asyncio.gather(*[run_one(sid) for sid in ready_ids])
        for sub_id, result in gathered:
            context[sub_id] = result
            subtask_map[sub_id]["status"] = "reviewing"
            subtask_map[sub_id]["result"] = result
            logger.info("[executor] %s → %s", sub_id,
                        "ok" if result.get("ok") else "failed")

    # 取第一个 ready 任务 id 供 reviewer 使用
    return {
        "subtask_map": subtask_map,
        "context": context,
        "current_subtask_id": ready_ids[0],
    }


async def reviewer_node(state: OrchestratorState) -> dict:
    """审查节点：对刚执行的子任务做逐项质量检查，决定 pass / retry / human"""
    subtask_map = state.get("subtask_map", {})
    current_id = state.get("current_subtask_id", "")

    if not current_id or current_id not in subtask_map:
        return {}

    subtask = subtask_map[current_id]
    result = subtask.get("result", {})
    retry_count = subtask.get("retry_count", 0)

    review = _reviewer.review(subtask, result, retry_count)
    action = review["action"]
    subtask["review_status"] = action
    subtask["review_score"] = review["score"]

    if action == "pass":
        subtask["status"] = "done"
        logger.info("[reviewer] %s → PASS (score=%.2f)", current_id, review["score"])

    elif action == "retry":
        subtask["retry_count"] = retry_count + 1
        subtask["status"] = "pending"  # 回到 pending 等待重试
        if subtask["result"] is None:
            subtask["result"] = {}
        subtask["result"]["review_feedback"] = review.get("feedback", "")
        # 如果 feedback 包含新搜索词，替换 args 中的 query 参数
        new_query = _extract_search_suggestion(review.get("feedback", ""))
        if new_query and subtask.get("tool") == "web_search":
            subtask["args"]["query"] = new_query
            logger.info("[reviewer] %s 更新搜索词: %s", current_id, new_query)
        logger.info("[reviewer] %s → RETRY #%d (score=%.2f): %s",
                    current_id, subtask["retry_count"], review["score"],
                    review.get("feedback", "")[:80])

    elif action == "human":
        subtask["status"] = "waiting_human"
        subtask["review_status"] = "blocked_human"
        logger.info("[reviewer] %s → HUMAN (score=%.2f)", current_id, review["score"])

    return {"subtask_map": subtask_map}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _extract_search_suggestion(feedback: str) -> str | None:
    """从 reviewer 反馈中提取建议的搜索词"""
    import re
    if not feedback:
        return None
    # 匹配 search:关键词 或 搜索:关键词 格式
    m = re.search(r'search[:：]\s*(.+?)(?:$|[,;，；。\n])', feedback, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 兜底：匹配引号中的内容
    m = re.search(r'”(.+?)”', feedback)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# 路由函数
# ---------------------------------------------------------------------------

def review_route(state: OrchestratorState) -> str:
    """根据 review 结果路由"""
    current_id = state.get("current_subtask_id", "")
    subtask_map = state.get("subtask_map", {})
    action = (subtask_map.get(current_id, {})).get("review_status", "pass")

    if action == "retry":
        return "execute"
    if action == "blocked_human":
        return "human_approval"  # 挂起等待人工审批

    # 当前任务审查完毕，检查是否还有同一批次的其他任务需要审查
    reviewing = [sid for sid, st in subtask_map.items()
                 if st.get("status") == "reviewing"]
    if reviewing:
        logger.info("[review_route] 还有 %d 个任务待审查: %s", len(reviewing), reviewing[0])
        return "review_next"

    return "continue"


def review_next_node(state: OrchestratorState) -> dict:
    """设置下一个待审查任务为当前任务"""
    subtask_map = state.get("subtask_map", {})
    reviewing = [sid for sid, st in subtask_map.items()
                 if st.get("status") == "reviewing"]
    if reviewing:
        return {"current_subtask_id": reviewing[0]}
    return {}


def continue_node(state: OrchestratorState) -> dict:
    """检查是否全部完成，设置最终状态"""
    subtask_map = state.get("subtask_map", {})
    pending = {sid for sid, st in subtask_map.items()
               if st.get("status") == "pending"}
    if pending:
        return {}
    done_count = sum(1 for st in subtask_map.values() if st.get("status") == "done")
    logger.info("[continue] 执行完毕: %d/%d 成功", done_count, len(subtask_map))
    return {"status": "done"}


def should_continue(state: OrchestratorState) -> str:
    """判断下一步：执行/重规划/汇总"""
    subtask_map = state.get("subtask_map", {})
    pending = {sid for sid, st in subtask_map.items()
               if st.get("status") == "pending"}
    if pending:
        return "execute"

    # 有阻塞或失败的任务 → 尝试重规划
    blocked_or_failed = {sid for sid, st in subtask_map.items()
                         if st.get("status") in ("failed", "blocked")}
    if blocked_or_failed:
        return "replan"

    return "aggregate"


async def replan_node(state: OrchestratorState) -> dict:
    """重规划节点：评估 DAG 状态，决定跳过/替换/调整依赖"""
    query = state.get("original_query", "")
    subtask_map = state.get("subtask_map", {})

    logger.info("[replan] 评估 DAG 状态...")
    result = _replan.evaluate(query, subtask_map)

    action = result.get("action", "none")
    logger.info("[replan] 决策: %s — %s", action, result.get("reason", ""))

    if action == "none":
        # 不做调整，直接让 aggregator 处理
        return {}

    # 应用调整
    for adj in result.get("adjustments", []):
        tid = adj.get("target_id", "")
        if tid in subtask_map:
            if adj.get("new_status"):
                subtask_map[tid]["status"] = adj["new_status"]
            if adj.get("new_depends_on") is not None:
                subtask_map[tid]["depends_on"] = adj["new_depends_on"]
            if adj.get("new_description"):
                subtask_map[tid]["description"] = adj["new_description"]
            logger.info("[replan] 调整 %s: status=%s deps=%s",
                        tid, adj.get("new_status"), adj.get("new_depends_on"))

    # 添加新子任务
    for new_st in result.get("new_subtasks", []):
        new_id = new_st.get("id", f"sub_replan_{len(subtask_map) + 1}")
        if new_id not in subtask_map:
            subtask_map[new_id] = new_st
            new_st.setdefault("status", "pending")
            new_st.setdefault("retry_count", 0)
            new_st.setdefault("review_status", "pending")
            new_st.setdefault("review_score", 0.0)
            new_st.setdefault("result", None)
            logger.info("[replan] 新增子任务: %s", new_id)

    return {"subtask_map": subtask_map}


def human_approval_node(state: OrchestratorState) -> dict:
    """人工审批节点：自动通过（接受不完美结果），不再阻塞流程"""
    subtask_map = state.get("subtask_map", {})
    current_id = state.get("current_subtask_id", "")
    subtask = subtask_map.get(current_id, {})

    score = subtask.get("review_score", 0)
    # 自动接受：标记为 done 但记录审阅结果
    subtask["status"] = "done"
    subtask["review_status"] = "auto_approved"
    logger.info("[human_approval] %s 自动通过 (score=%.2f)，已接受不完美结果", current_id, score)

    return {"subtask_map": subtask_map, "human_interrupt": False}


async def aggregator_node(state: OrchestratorState) -> dict:
    """汇总节点：整合所有子任务结果，生成最终回答"""
    query = state.get("original_query", "")
    subtask_map = state.get("subtask_map", {})

    logger.info("[aggregator] 开始汇总 %d 个子任务", len(subtask_map))
    result = _aggregator.aggregate(query, subtask_map)

    if result.get("ok"):
        logger.info("[aggregator] 汇总完成")
        return {"final_output": result["data"], "status": "done"}
    else:
        logger.warning("[aggregator] 汇总失败: %s", result.get("error"))
        return {"final_output": "汇总失败", "status": "done"}


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

def build_graph():
    """构建 LangGraph 编排图，带 MemorySaver 支持 interrupt"""
    workflow = StateGraph(OrchestratorState)

    workflow.add_node("plan", plan_node)
    workflow.add_node("execute_one", execute_one_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("review_next", review_next_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("continue", continue_node)
    workflow.add_node("replan", replan_node)
    workflow.add_node("aggregate", aggregator_node)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "execute_one")

    # execute_one → reviewer
    workflow.add_edge("execute_one", "reviewer")

    # reviewer 路由
    workflow.add_conditional_edges(
        "reviewer",
        review_route,
        {
            "execute": "execute_one",
            "human_approval": "human_approval",
            "review_next": "review_next",
            "continue": "continue",
        }
    )
    workflow.add_edge("review_next", "reviewer")

    # human_approval 后 → continue
    workflow.add_edge("human_approval", "continue")

    # continue 路由
    workflow.add_conditional_edges(
        "continue",
        should_continue,
        {
            "execute": "execute_one",
            "replan": "replan",
            "aggregate": "aggregate",
        }
    )

    workflow.add_edge("replan", "continue")
    workflow.add_edge("aggregate", END)

    # 带 memory saver 以支持 interrupt 挂起/恢复
    return workflow.compile(checkpointer=MemorySaver())


# 模块级编译图
graph = build_graph()
