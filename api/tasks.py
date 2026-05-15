"""任务提交、状态查询、人工审批"""
import uuid

from fastapi import APIRouter, HTTPException
from langgraph.types import Command

from orchestrator.graph import graph

router = APIRouter(prefix="/v1")


def _build_summary(result: dict) -> list[dict]:
    """从完整 subtask_map 中提取前端需要的摘要字段"""
    subtask_map = result.get("subtask_map", {})
    return [
        {
            "id": st.get("id"),
            "description": st.get("description"),
            "tool": st.get("tool"),
            "status": st.get("status"),
            "review_score": st.get("review_score"),
        }
        for st in subtask_map.values()
    ]


def _find_waiting_human(result: dict) -> list[dict]:
    """找出所有等待人工审批的子任务"""
    subtask_map = result.get("subtask_map", {})
    waiting = []
    for sid, st in subtask_map.items():
        if st.get("status") == "waiting_human":
            waiting.append({
                "subtask_id": sid,
                "description": st.get("description", ""),
                "result": st.get("result", {}),
                "review_score": st.get("review_score", 0),
                "retry_count": st.get("retry_count", 0),
            })
    return waiting


# ---------------------------------------------------------------------------
# 任务提交
# ---------------------------------------------------------------------------

@router.post("/task/submit")
async def submit_task_v2(query: str):
    """提交任务（规范化端点），返回 thread_id"""
    thread_id = uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": thread_id}}

    result = await graph.ainvoke({"original_query": query}, config)
    waiting = _find_waiting_human(result)

    return {
        "ok": True,
        "thread_id": thread_id,
        "status": result.get("status", "executing"),
        "final_output": result.get("final_output", ""),
        "subtasks": _build_summary(result),
        "waiting_human": waiting,
    }


# 旧端点保留兼容
@router.post("/task")
async def submit_task_legacy(query: str):
    """[已废弃] 请使用 POST /v1/task/submit"""
    return await submit_task_v2(query)


@router.get("/task/{thread_id}/status")
async def get_task_status(thread_id: str):
    """查询任务状态（通过 LangGraph checkpoint）"""
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)

    if not state or not state.values:
        raise HTTPException(status_code=404, detail=f"任务 {thread_id} 不存在或已过期")

    return {
        "ok": True,
        "thread_id": thread_id,
        "status": state.values.get("status", "unknown"),
        "final_output": state.values.get("final_output", ""),
        "subtasks": _build_summary(state.values),
    }


# ---------------------------------------------------------------------------
# 状态查询（兼容旧接口）
# ---------------------------------------------------------------------------

@router.get("/planner")
async def get_task(query: str):
    """GET 方式提交任务（简洁版，不返回 thread_id）"""
    result = await graph.ainvoke({"original_query": query})

    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result.get("final_output", "执行失败"))

    return {
        "ok": True,
        "final_output": result.get("final_output", ""),
        "subtasks": _build_summary(result),
    }


@router.get("/planner/debug")
async def get_task_debug(query: str):
    """调试接口：返回全部内部状态"""
    result = await graph.ainvoke({"original_query": query})

    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result.get("final_output", "执行失败"))

    return {
        "ok": True,
        "final_output": result.get("final_output", ""),
        "subtasks": result.get("subtask_map", {}),
        "context": result.get("context", {}),
    }


# ---------------------------------------------------------------------------
# 人工审批
# ---------------------------------------------------------------------------

@router.post("/task/{thread_id}/approve")
async def approve_task(thread_id: str, approved: bool = True, comment: str = ""):
    """人工审批：批准或驳回等待中的子任务"""
    config = {"configurable": {"thread_id": thread_id}}

    # 用 Command(resume=...) 恢复被 interrupt() 挂起的图
    result = await graph.ainvoke(
        Command(resume={"approved": approved, "comment": comment}),
        config,
    )

    waiting = _find_waiting_human(result)

    return {
        "ok": True,
        "thread_id": thread_id,
        "status": result.get("status", "executing"),
        "final_output": result.get("final_output", ""),
        "subtasks": _build_summary(result),
        "waiting_human": waiting,  # 可能还有其他任务需要审批
    }
