"""审查 Agent：对子任务执行结果逐项打分，决定通过/重试/人工审批"""
import json
import os

from agents.base import BaseAgent


class ReviewerAgent(BaseAgent):
    """使用更强推理模型做质量把关"""

    def __init__(self):
        # Reviewer 使用与 Planner 同级别的强推理模型
        super().__init__(name="reviewer", model_name=os.getenv("PLAN_MODEL"))

    def _get_system_prompt(self) -> str:
        from agents.prompts import REVIEWER_SYSTEM_PROMPT
        return REVIEWER_SYSTEM_PROMPT

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def review(self, subtask: dict, result: dict, retry_count: int = 0) -> dict:
        """审查一次执行结果

        Args:
            subtask: 包含 description、expected_output 的子任务定义
            result: executor 返回的 {"ok": ..., "data": ..., "error": ...}
            retry_count: 当前已重试次数

        Returns:
            {"action": "pass"|"retry"|"human", "score": 0-1, "checks": [...], "feedback": ...}
        """
        # 工具执行失败 → 直接标记为需重试，不浪费 LLM 调用
        if not result.get("ok"):
            return {
                "action": "retry" if retry_count < 2 else "human",
                "score": 0.0,
                "checks": [
                    {"item": "执行结果", "pass": False,
                     "detail": f"工具/LLM 返回错误: {result.get('error', '未知错误')}"}
                ],
                "feedback": result.get("error", ""),
            }

        # 工具/LLM 成功 → LLM 做定性审查
        review_output = self._llm_review(subtask, result)
        score = review_output.get("overall_score", 0.0)
        passed = review_output.get("passed", False)

        if passed or score >= 0.8:
            action = "pass"
        elif score >= 0.5 and retry_count < 2:
            action = "retry"
        elif score >= 0.5:
            action = "human"
        else:
            action = "retry" if retry_count < 2 else "human"

        if_failed = review_output.get("if_failed") or {}
        return {
            "action": action,
            "score": score,
            "checks": review_output.get("checks") or [],
            "feedback": if_failed.get("specific_fix", ""),
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _llm_review(self, subtask: dict, result: dict) -> dict:
        """调用 LLM 做逐项审查"""
        expected = subtask.get("expected_output", "")
        description = subtask.get("description", "")
        tool = subtask.get("tool", "none")
        data = result.get("data", "")

        # 截断过长数据，避免 token 浪费
        data_str = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
        if len(data_str) > 2000:
            data_str = data_str[:2000] + "...(截断)"

        # 区分任务类型，帮助 reviewer 调整评分标准
        task_type = "LLM直接回答" if tool == "none" else f"工具调用（{tool}）"

        prompt = f"""## 子任务描述
{description}

## 任务类型
{task_type}

## 期望输出
{expected}

## 实际输出
{data_str}

请逐项审查以上输出，根据任务类型调整评分标准，返回 JSON。"""

        return self.structured_invoke(
            prompt,
            {
                "checks": [
                    {"item": "维度名", "pass": True, "detail": "具体判断依据"}
                ],
                "overall_score": 0.9,
                "passed": True,
                "if_failed": {
                    "reason": "",
                    "specific_fix": ""
                }
            }
        )
