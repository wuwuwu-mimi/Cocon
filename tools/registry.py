import asyncio
from typing import Callable, Dict


class ToolRegistry:
    """工具注册中心：统一管理所有可调用工具"""

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, dict] = {}
        self._acl: Dict[str, list] = {}

    def register(self, name: str, func: Callable, schema: dict, acl: list = None):
        """
        注册工具
        - name: 工具名
        - func: async 函数
        - schema: OpenAI Function Calling 格式的 JSON Schema
        - acl: 允许调用此工具的 Agent 列表（None = 全部允许）
        """
        self._tools[name] = func
        self._schemas[name] = schema

        if acl:
            self._acl[name] = acl

    def get_schema(self, name: str) -> dict:
        return self._schemas.get(name, {})

    def list_tools(self) -> list:
        """返回所有工具的 Function Calling Schema"""
        return [
            {
                "type": "function",
                "function": {"name": name, **schema},
            }
            for name, schema in self._schemas.items()
        ]

    async def call(self, name: str, **kwargs) -> dict:
        """调用工具"""
        if name not in self._tools:
            return {"ok": False, "error": f"未知工具: {name}"}

        try:
            result = await asyncio.wait_for(
                self._tools[name](**kwargs),
                timeout=30,
            )
            return {"ok": True, "data": result}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "工具调用超时"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
