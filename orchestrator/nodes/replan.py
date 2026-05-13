"""重规划 Agent：执行失败/阻塞时动态调整 DAG"""
import json
import os

from agents.base import BaseAgent


class ReplanAgent(BaseAgent):
    """当子任务阻塞或失败时，评估 DAG 并决策调整方案"""

    def __init__(self):
        super().__init__(name="replan", model_name=os.getenv("PLAN_MODEL"))

    def _get_system_prompt(self) -> str:
        from agents.prompts import REPLAN_SYSTEM_PROMPT
        return REPLAN_SYSTEM_PROMPT

    def evaluate(self, original_query: str, subtask_map: dict) -> dict:
        """评估当前 DAG 状态，决策是否需要调整

        Args:
            original_query: 用户原始问题
            subtask_map: {sub_id: Subtask} 包含所有子任务及状态

        Returns:
            {"action": "skip"|"replace"|"adjust_deps"|"none",
             "adjustments": [...], "new_subtasks": [...]}
        """
        # 快速判断：没有任何阻塞或失败的任务，直接跳过
        blocked_or_failed = [
            sid for sid, st in subtask_map.items()
            if st.get("status") in ("failed", "blocked")
        ]
        if not blocked_or_failed:
            return {"action": "none", "reason": "所有任务已完成或通过"}

        # 构建状态摘要，调用 LLM 做决策
        summary = self._build_state_summary(subtask_map)
        prompt = f"""## 用户问题
{original_query}

## 子任务状态
{summary}

## 阻塞/失败的任务
{', '.join(blocked_or_failed)}

请评估当前 DAG 状态，决定是否需要调整计划。"""

        try:
            result = self.structured_invoke(
                prompt,
                {
                    "action": "none",
                    "reason": "",
                    "adjustments": [
                        {
                            "target_id": "sub_x",
                            "new_status": "pending",
                            "new_depends_on": [],
                            "new_description": ""
                        }
                    ],
                    "new_subtasks": [
                        {
                            "id": "sub_replan_1",
                            "description": "新任务描述",
                            "tool": "web_search",
                            "args": {},
                            "depends_on": [],
                            "expected_output": "预期输出"
                        }
                    ]
                }
            )
            return result or {"action": "none", "reason": "LLM 返回空"}
        except Exception as e:
            return {"action": "none", "reason": f"重规划失败: {str(e)}"}

    @staticmethod
    def _build_state_summary(subtask_map: dict) -> str:
        """构建子任务状态摘要"""
        parts = []
        for sub_id, st in subtask_map.items():
            status = st.get("status", "unknown")
            desc = st.get("description", "")
            deps = st.get("depends_on", [])
            tool = st.get("tool", "none")
            review_status = st.get("review_status", "")
            review_score = st.get("review_score", 0)

            parts.append(
                f"- {sub_id} [{status}]: {desc}\n"
                f"  tool={tool}, deps={deps}, review={review_status}({review_score})"
            )
        return "\n".join(parts)
