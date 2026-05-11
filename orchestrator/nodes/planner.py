"""将自然语言任务拆解成多个任务"""
import os

from agents.base import BaseAgent
from dotenv import load_dotenv

from orchestrator.state import Subtask
from tools import registry

load_dotenv()


class PlannerAgent(BaseAgent):
    """拆解任务使用deepseek-v4-pro"""
    plan_model = os.getenv("PLAN_MODEL")

    def __init__(self):
        super().__init__(name="planner", model_name=self.plan_model)

    def _get_system_prompt(self) -> str:
        from agents.prompts import PLANNER_SYSTEM_PROMPT
        return PLANNER_SYSTEM_PROMPT.format(tools_description=registry.list_tools())

    def plan(self, user_query: str) -> dict:
        """生成计划任务，返回 Subtask 字典"""
        # output_schema 作为示例格式传递给 structured_invoke，
        # 该方法会将其序列化后追加到 prompt 中，引导 LLM 按此结构输出
        res = self.structured_invoke(
            user_query, {
                "subtasks": [
                    {
                        "id": "sub_1",
                        "description": "子任务的具体操作描述",
                        "tool": "工具名或 none",
                        "args": {"参数名": "参数值或 {{sub_x.output}} 引用前置任务结果"},
                        "depends_on": [],
                        "expected_output": "预期输出的具体描述，用于后续审查"
                    }
                ],
                "parallel_groups": [["sub_1"], ["sub_2", "sub_3"]]
            }
        )
        # 将 LLM 原始输出转换为 Subtask 字典供编排器使用
        return self.plan_to_subtask_map(res)

    @staticmethod
    def plan_to_subtask_map(plan: dict) -> dict:
        """将 Planner 输出转换为 Subtask 字典"""
        # 防御：plan 为空或缺少 subtasks 时返回空字典，避免 KeyError
        if not plan or "subtasks" not in plan:
            return {}
        task_map = {}
        for st in plan["subtasks"]:
            # 跳过缺少 id 的无效子任务
            if "id" not in st:
                continue
            # 使用 .get() 防御 LLM 输出缺少字段的情况
            task_map[st["id"]] = Subtask(
                id=st["id"],
                description=st.get("description", ""),
                tool=st.get("tool", "none"),
                args=st.get("args", {}),
                depends_on=st.get("depends_on", []),
                expected_output=st.get("expected_output", ""),
                status="pending",
                result=None,
                retry_count=0,
                review_status="pending",
                review_score=0.0,
            )
        return task_map
