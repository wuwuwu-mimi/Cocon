"""任务提交与执行"""
from fastapi import APIRouter, HTTPException
from orchestrator.graph import graph

router = APIRouter(prefix="/v1")


@router.get("/planner")
async def get_task(query: str):
    """规划 + 执行：用户输入自然语言任务，返回拆解与执行结果"""
    result = await graph.ainvoke({"original_query": query})

    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result.get("final_output", "执行失败"))

    return {
        "ok": True,
        "subtasks": result.get("subtask_map", {}),
        "context": result.get("context", {}),
    }
