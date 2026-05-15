import logging
from .registry import ToolRegistry
from .builtin import BUILTIN_TOOLS_MANIFEST

logger = logging.getLogger(__name__)

registry = ToolRegistry()

for tool in BUILTIN_TOOLS_MANIFEST:
    registry.register(
        name=tool["name"],
        func=tool["func"],
        schema=tool["schema"]
    )

_mcp_manager = None


async def init_mcp():
    """启动 MCP Server 并将工具注册到 registry（main.py startup 调用）"""
    global _mcp_manager
    from tools.mcp.manager import MCPManager
    _mcp_manager = MCPManager()
    mcp_tools = await _mcp_manager.load_all()
    for t in mcp_tools:
        # 用闭包捕获 tool_name，避免 lambda 延迟绑定问题
        async def _call_mcp(tool_name=t["name"], **kwargs):
            return await _mcp_manager.call(tool_name, **kwargs)
        registry.register(
            name=t["name"],
            func=_call_mcp,
            schema={"description": t["description"], "parameters": t["parameters"]},
        )
        logger.info("[mcp] 已注册: %s", t["name"])


__all__ = ["registry", "init_mcp"]