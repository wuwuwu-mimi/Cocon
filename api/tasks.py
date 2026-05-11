"""任务提交 审批"""
from fastapi import APIRouter, HTTPException
from orchestrator.nodes.planner import PlannerAgent

# 路由定义
router = APIRouter(prefix="/v1")

# 模块级单例，避免每次请求重复创建 ChatOpenAI 客户端
_planner = PlannerAgent()


@router.get("/planner")
async def get_task(query: str):
    res = _planner.plan(query)

    print(f"DEBUG: Planner output type: {type(res)}")
    print(f"DEBUG: Planner output value: {res}")

    # plan() 内部已做空值防御，返回空字典同样视为规划失败
    if not res:
        raise HTTPException(status_code=500, detail="模型未能生成有效的规划结果，请检查提示词或更换更强的模型")
    return {"task": res}
