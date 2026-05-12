"""LangGraph 编排图：plan → execute → END

后续扩展点：
  - execute_node 可拆为 execute_one + conditional loop 实现逐任务执行
  - plan → executor 之间插入 reviewer_node 做质量把关
  - executor 后加 conditional edge → replan_node 处理动态重规划
"""
import logging

from langgraph.graph import StateGraph, END

from orchestrator.state import OrchestratorState
from orchestrator.nodes.planner import PlannerAgent
from orchestrator.nodes.executor import ExecutorAgent

logger = logging.getLogger(__name__)

# 模块级单例
_planner = PlannerAgent()
_executor = ExecutorAgent()


# ---------------------------------------------------------------------------
# 节点函数
# ---------------------------------------------------------------------------

async def plan_node(state: OrchestratorState) -> dict:
    """规划节点：用户查询 → 子任务 DAG"""
    query = state["original_query"]
    logger.info("[plan_node] 开始规划: %s", query)

    subtask_map = _planner.plan(query)
    if not subtask_map:
        logger.warning("[plan_node] 规划失败，未生成子任务")
        return {"status": "failed", "final_output": "规划失败，未生成子任务"}

    logger.info("[plan_node] 完成: %d 个子任务", len(subtask_map))
    return {
        "subtask_map": subtask_map,
        "status": "executing",
    }


async def executor_node(state: OrchestratorState) -> dict:
    """执行节点：按依赖拓扑排序，逐批次执行所有子任务

    后续可拆分为迭代模式（execute_one + conditional loop），
    以便在每次执行后插入 reviewer 审查。
    """
    subtask_map = state.get("subtask_map", {})
    if not subtask_map:
        return {"status": "failed", "final_output": "无子任务可执行"}

    context = state.get("context", {})
    pending = {sid for sid, st in subtask_map.items()
               if st.get("status") not in ("done", "failed", "blocked")}
    completed = {sid for sid, st in subtask_map.items()
                 if st.get("status") in ("done", "failed", "blocked")}
    all_ids = set(subtask_map.keys())

    while pending:
        # 找出依赖已满足或依赖不存在的任务
        ready = []
        for sid in pending:
            deps = subtask_map[sid].get("depends_on", [])
            missing = [d for d in deps if d not in all_ids]
            if missing:
                logger.warning("[executor_node] %s 依赖不存在: %s，标记为 blocked", sid, missing)
                subtask_map[sid]["status"] = "blocked"
                completed.add(sid)
                continue
            if all(dep in completed for dep in deps):
                ready.append(sid)

        if not ready:
            # 死锁：有剩余任务但都不满足依赖条件
            for sid in pending - completed:
                subtask_map[sid]["status"] = "blocked"
                logger.warning("[executor_node] %s 因依赖无法满足被阻塞", sid)
            break

        # 串行执行当前批次（后续可改为 asyncio.gather 并行）
        for sub_id in ready:
            subtask = subtask_map[sub_id]
            logger.info("[executor_node] 执行: %s (tool=%s)", sub_id, subtask.get("tool"))
            result = await _executor.execute(subtask, context)
            context[sub_id] = result
            subtask["status"] = "done" if result.get("ok") else "failed"
            subtask["result"] = result
            completed.add(sub_id)
            logger.info("[executor_node] %s → %s", sub_id, subtask["status"])

        pending -= completed

    done_count = sum(1 for st in subtask_map.values() if st.get("status") == "done")
    logger.info("[executor_node] 执行完成: %d/%d 成功", done_count, len(subtask_map))

    return {
        "subtask_map": subtask_map,
        "context": context,
        "status": "done",
    }


# ---------------------------------------------------------------------------
# 构建图
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """构建 LangGraph 编排图"""
    workflow = StateGraph(OrchestratorState)

    # 注册节点
    workflow.add_node("plan", plan_node)
    workflow.add_node("executor", executor_node)

    # 边：plan → executor → END
    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "executor")
    workflow.add_edge("executor", END)

    return workflow.compile()


# 模块级编译图，复用同一个图实例
graph = build_graph()
