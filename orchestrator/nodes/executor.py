"""负责执行拆分后的小任务"""
import json
import os
import re

from agents.base import BaseAgent
from orchestrator.state import Subtask
from tools import registry


class ExecutorAgent(BaseAgent):

    def __init__(self):
        super().__init__(name="executor", model_name=os.getenv("EXECUTOR_MODEL"))

    def _get_system_prompt(self) -> str:
        from agents.prompts import EXECUTOR_SYSTEM_PROMPT
        return EXECUTOR_SYSTEM_PROMPT.format(tools_description=registry.list_tools())

    async def execute(self, subtask: Subtask, context: dict = None) -> dict:
        """执行单条子任务
        :param subtask: planner 输出的 Subtask 字典
        :param context: 前置任务结果，key=subtask_id, value={"ok": True, "data": ...}
        :return: {"ok": True, "data": ...} 或 {"ok": False, "error": ...}
        """
        context = context or {}

        # 1. 解析 args 中的 {{sub_x.output}} 占位符，注入前置任务结果
        raw_args = subtask.get("args", {})
        resolved_args = self._resolve_placeholders(raw_args, context)

        # 2. 有工具则调工具，无工具则 LLM 直接推理
        tool_name = subtask.get("tool", "none")
        if tool_name and tool_name != "none":
            return await self._run_tool(tool_name, resolved_args)
        return self._run_llm(subtask, resolved_args, context)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _run_tool(self, tool_name: str, args: dict) -> dict:
        """调用已注册的工具，传入 caller_id 做 ACL 校验"""
        try:
            result = await registry.call(tool_name, caller_id=self.name, **args)
            return result
        except Exception as e:
            return {"ok": False, "error": f"工具调用异常: {str(e)}"}

    def _run_llm(self, subtask: Subtask, args: dict, context: dict) -> dict:
        """无工具时由 LLM 直接推理作答"""
        prompt_parts = [f"## 任务\n{subtask.get('description', '')}"]
        if subtask.get("expected_output"):
            prompt_parts.append(f"## 预期输出\n{subtask['expected_output']}")
        if args:
            prompt_parts.append(f"## 参数\n{json.dumps(args, ensure_ascii=False)}")
        if context:
            prompt_parts.append(f"## 前置任务结果\n{json.dumps(context, ensure_ascii=False)}")

        try:
            response = self.invoke("\n\n".join(prompt_parts))
            return {"ok": True, "data": response}
        except Exception as e:
            return {"ok": False, "error": f"LLM 调用异常: {str(e)}"}

    def _resolve_placeholders(self, args: dict, context: dict) -> dict:
        """递归替换 args 中的 {{sub_x.output}} 占位符"""
        resolved = {}
        for key, value in args.items():
            resolved[key] = self._replace_refs(value, context)
        return resolved

    def _replace_refs(self, value, context: dict):
        """递归处理 value，替换字符串中的 {{sub_id.path}} 占位符"""
        if isinstance(value, str):
            return re.sub(
                r"\{\{(.+?)\}\}",
                lambda m: self._lookup_context(m.group(1).strip(), context),
                value,
            )
        if isinstance(value, dict):
            return {k: self._replace_refs(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace_refs(v, context) for v in value]
        return value

    @staticmethod
    def _lookup_context(path: str, context: dict) -> str:
        """按路径从 context 取值，path 格式: sub_id.output.data.xxx
        第一段是 subtask_id，后续段逐层访问该任务的结果字典"""
        parts = path.split(".")
        subtask_id = parts[0]
        if subtask_id not in context:
            return f"【未找到前置任务: {subtask_id}】"
        current = context[subtask_id]
        for part in parts[1:]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                break
        if isinstance(current, (dict, list)):
            return json.dumps(current, ensure_ascii=False)
        # 保留原始类型（int/float/bool/None），避免 "5" != 5 导致工具调用失败
        if isinstance(current, (int, float, bool, type(None))):
            return current
        return str(current)
