"""汇总 Agent：整合所有子任务结果，生成最终回答"""
import json
import os

from agents.base import BaseAgent


class AggregatorAgent(BaseAgent):
    """将多个子任务结果整合为一份连贯的最终输出"""

    def __init__(self):
        super().__init__(name="aggregator", model_name=os.getenv("EXECUTOR_MODEL"))

    def _get_system_prompt(self) -> str:
        from agents.prompts import AGGREGATOR_SYSTEM_PROMPT
        return AGGREGATOR_SYSTEM_PROMPT

    def aggregate(self, original_query: str, subtask_map: dict) -> dict:
        """汇总所有子任务结果

        Args:
            original_query: 用户原始问题
            subtask_map: {sub_id: Subtask} 包含所有子任务及其执行结果

        Returns:
            {"ok": True, "data": "Markdown格式的最终回答"}
        """
        summary = self._build_summary(subtask_map)

        prompt = f"""## 用户问题
{original_query}

## 子任务执行摘要
{summary}

请整合以上所有信息，生成一份完整的最终回答。"""

        try:
            response = self.invoke(prompt)
            return {"ok": True, "data": response}
        except Exception as e:
            return {"ok": False, "error": f"汇总失败: {str(e)}"}

    @staticmethod
    def _build_summary(subtask_map: dict) -> str:
        """构建子任务执行摘要，供 aggregator LLM 阅读"""
        parts = []
        for sub_id, st in subtask_map.items():
            status = st.get("status", "unknown")
            desc = st.get("description", "")
            tool = st.get("tool", "none")
            result = st.get("result") or {}

            status_icon = {
                "done": "[成功]", "failed": "[失败]",
                "blocked": "[阻塞]", "pending": "[未执行]",
                "reviewing": "[审查中]",
            }.get(status, f"[{status}]")

            data = result.get("data", "")
            error = result.get("error", "")

            parts.append(f"### {sub_id} {status_icon}: {desc}")
            parts.append(f"工具: {tool}")

            if error:
                parts.append(f"错误: {error}")
            elif data:
                data_str = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)
                if len(data_str) > 2000:
                    data_str = data_str[:2000] + "...(截断)"
                parts.append(f"结果:\n{data_str}")
            parts.append("")

        return "\n".join(parts) if parts else "无子任务"
