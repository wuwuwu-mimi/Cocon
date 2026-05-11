import os
from abc import ABC, abstractmethod
from typing import Optional
from dotenv import load_dotenv

from langchain_openai import OpenAI, ChatOpenAI

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

        prompt = self.system_prompt
        prompt += f"\n\n你必须返回 JSON，格式如下：\n{json.dumps(output_schema, ensure_ascii=False, indent=2)}"

        raw = self.invoke(user_message, context)

        # 提取 JSON（处理 LLM 输出可能包裹在 ```json 中）
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        return json.loads(raw.strip())

