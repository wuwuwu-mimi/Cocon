"""MCP 进程管理器：启动/监控/清理 MCP Server 子进程"""
import asyncio
import atexit
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

from tools.mcp.client import MCPClient

IDLE_TIMEOUT = 300  # 5 分钟无调用自动关闭
_config_path = "mcp_config.json"


class MCPManager:
    """管理所有 MCP Server 客户端"""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tools_map: dict[str, MCPClient] = {}  # short_name → client
        self._tool_names: dict[str, str] = {}  # short_name → original_name
        atexit.register(self.cleanup_all)

    async def load_all(self) -> list[dict]:
        """加载 mcp_config.json，启动所有 Server，返回完整工具列表"""
        import sys
        config = self._load_config()
        servers = config.get("mcpServers", {})

        tools = []
        for name, cfg in servers.items():
            # 解决 Windows 下 "python" 不在 PATH 或用错解释器的问题
            command = cfg["command"]
            if command in ("python", "python3"):
                command = sys.executable

            logger.info("[mcp] 启动 Server: %s (%s %s)",
                        name, command, " ".join(cfg.get("args", [])))
            client = MCPClient(
                name=name,
                command=command,
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
            )
            ok = await client.connect()
            if ok:
                self._clients[name] = client
                server_tools = await client.list_tools()
                for t in server_tools:
                    # 简洁命名：github_trending 而不是 mcp:github-trending:get_github_trending
                    original = t['name']
                    # 去掉 "get_" 前缀，命名更自然
                    short_name = original.removeprefix("get_")
                    tool_name = f"{name}_{short_name}" if short_name else f"{name}_{original}"
                    self._tools_map[tool_name] = client
                    self._tool_names[tool_name] = original
                    tools.append({
                        "name": tool_name,
                        "description": t.get("description", ""),
                        "parameters": t.get("inputSchema", {
                            "type": "object",
                            "properties": {},
                        }),
                    })
            else:
                logger.warning("[mcp] %s 启动失败，跳过", name)

        logger.info("[mcp] 已加载 %d 个 Server，共 %d 个工具",
                    len(self._clients), len(tools))
        return tools

    async def call(self, short_name: str, **kwargs) -> dict:
        """调用 MCP 工具（用注册时的短名称）"""
        client = self._tools_map.get(short_name)
        if not client:
            return {"ok": False, "error": f"未知 MCP 工具: {short_name}"}
        original_name = self._tool_names.get(short_name, short_name)
        return await client.call_tool(original_name, kwargs)

    def cleanup_all(self):
        """进程退出时清理所有子进程"""
        for name, client in list(self._clients.items()):
            try:
                asyncio.get_event_loop().run_until_complete(client.shutdown())
            except Exception:
                pass

    def _load_config(self) -> dict:
        """加载 mcp_config.json"""
        if os.path.exists(_config_path):
            with open(_config_path, encoding="utf-8") as f:
                return json.load(f)
        return {}
