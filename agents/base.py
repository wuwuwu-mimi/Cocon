import os
from abc import ABC, abstractmethod
from typing import Optional
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI

load_dotenv()


class BaseAgent(ABC):
    def __init__(self, name: Optional[str], model_name: Optional[str]):
        self.name = name
        self.llm = ChatOpenAI(
            model=model_name or os.getenv("EXECUTOR_MODEL"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            temperature=0.1
        )

        self.system_prompt = self._get_system_prompt()

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """子类实现：返回 system prompt"""
        pass

    def invoke(self, user_message: str, context: dict = None) -> str:
        """调用llm"""
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [SystemMessage(content=self.system_prompt)]

        if context:
            messages.append(
                HumanMessage(content=f"上下文：\n{context}\n\n任务：\n{user_message}")
            )
        else:
            messages.append(HumanMessage(content=user_message))

        resp = self.llm.invoke(messages)
        return resp.content

    def structured_invoke(self, user_message: str, output_schema: dict, context: dict = None) -> dict:
        """调用 LLM 并返回结构化 JSON"""
        import json
        import logging
        import re

        logger = logging.getLogger(__name__)

        prompt = self.system_prompt
        prompt += f"\n\n你必须返回 JSON，格式如下：\n{json.dumps(output_schema, ensure_ascii=False, indent=2)}"

        raw = self.invoke(user_message, context)

        # 提取 JSON（处理 LLM 输出可能包裹在 ```json 中）
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试修复常见的 LLM 输出错误
            fixed = self._repair_json(raw)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                logger.warning("LLM 返回了无法解析的 JSON，原始内容:\n%s", raw)
                raise ValueError(f"LLM 返回了无法解析的 JSON，请检查模型输出质量。原始内容前200字符: {raw[:200]}")

    @staticmethod
    def _repair_json(raw: str) -> str:
        """修复常见的 JSON 格式错误"""
        import re
        # 去掉尾部多余的逗号
        raw = re.sub(r',\s*}', '}', raw)
        raw = re.sub(r',\s*]', ']', raw)
        # 去掉 JSON 之外的前缀/后缀文字
        first_brace = raw.find('{')
        first_bracket = raw.find('[')
        if first_brace == -1 and first_bracket == -1:
            return raw
        start = min(i for i in [first_brace, first_bracket] if i != -1)
        raw = raw[start:]
        last_brace = raw.rfind('}')
        last_bracket = raw.rfind(']')
        end = max(last_brace, last_bracket)
        if end != -1:
            raw = raw[:end + 1]
        return raw

