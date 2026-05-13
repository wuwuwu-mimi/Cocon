"""精简 Agent：将长篇报告压缩为飞书消息格式"""
import os

from agents.base import BaseAgent


class SummarizerAgent(BaseAgent):

    def __init__(self):
        super().__init__(name="summarizer", model_name=os.getenv("EXECUTOR_MODEL"))

    def _get_system_prompt(self) -> str:
        from agents.prompts import SUMMARIZER_SYSTEM_PROMPT
        return SUMMARIZER_SYSTEM_PROMPT

    def summarize(self, final_output: str) -> dict:
        if not final_output:
            return {"ok": False, "error": "无内容可精简"}

        prompt = f"请将以下报告精简为飞书消息格式，3-5条要点+信息来源链接：\n\n{final_output[:4000]}"

        try:
            response = self.invoke(prompt)
            return {"ok": True, "data": response}
        except Exception as e:
            return {"ok": False, "error": f"精简失败: {str(e)}"}
