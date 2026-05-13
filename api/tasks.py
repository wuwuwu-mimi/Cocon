"""任务提交与执行"""
from fastapi import APIRouter, HTTPException
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


@router.get("/planner")
async def get_task(query: str):
    """规划 + 执行：返回精简结果（final_output + 子任务摘要）"""
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
    """调试接口：返回全部内部状态（子任务详情 + 上下文 + 审查结果）"""
    result = await graph.ainvoke({"original_query": query})

    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result.get("final_output", "执行失败"))

    return {
        "ok": True,
        "final_output": result.get("final_output", ""),
        "subtasks": result.get("subtask_map", {}),
        "context": result.get("context", {}),
    }
