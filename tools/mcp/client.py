"""MCP JSON-RPC 2.0 客户端（stdio 传输）"""
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """通过 stdio 与 MCP Server 通信"""

    def __init__(self, name: str, command: str, args: list[str] = None,
                 env: dict[str, str] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._tools: list[dict] = []

    async def connect(self) -> bool:
        """启动子进程并完成 JSON-RPC 握手"""
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**__import__('os').environ, **self.env},
            )
            # 读取 stdout 响应的后台任务
            self._reader_task = asyncio.create_task(self._read_loop())

            # JSON-RPC initialize
            result = await self._send("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cocon", "version": "0.1.0"},
            })
            if not result:
                return False

            # 发送 initialized 通知
            self._send_notification("notifications/initialized", {})

            # 获取工具列表
            tools = await self._send("tools/list", {})
            self._tools = tools.get("tools", []) if tools else []
            logger.info("[mcp:%s] 已连接，%d 个工具", self.name, len(self._tools))
            return True

        except Exception as e:
            logger.warning("[mcp:%s] 连接失败: %s", self.name, str(e))
            return False

    async def list_tools(self) -> list[dict]:
        """返回工具列表"""
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """调用工具"""
        result = await self._send("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result is None:
            return {"ok": False, "error": "mcp_unavailable"}
        # MCP 返回 {content: [{type: "text", text: "..."}]} 或 {content: [{type: "resource", ...}]}
        content = result.get("content", [])
        texts = []
        for c in content:
            if c.get("type") == "text":
                texts.append(c.get("text", ""))
            elif c.get("type") == "resource":
                texts.append(json.dumps(c, ensure_ascii=False))
        text = "\n".join(texts)
        is_error = result.get("isError", False)
        if is_error:
            return {"ok": False, "error": text}
        return {"ok": True, "data": text if text else result}

    async def shutdown(self):
        """关闭连接"""
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send(self, method: str, params: dict) -> dict | None:
        """发送请求并等待响应"""
        rid = self._next_id()
        msg = json.dumps({
            "jsonrpc": "2.0", "id": rid,
            "method": method, "params": params,
        })
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = future

        try:
            self._proc.stdin.write((msg + "\n").encode())
            await self._proc.stdin.drain()
            return await asyncio.wait_for(future, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            logger.warning("[mcp:%s] %s 超时", self.name, method)
            return None
        except Exception as e:
            self._pending.pop(rid, None)
            logger.warning("[mcp:%s] %s 错误: %s", self.name, method, str(e))
            return None

    def _send_notification(self, method: str, params: dict):
        """发送通知（无需响应）"""
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method, "params": params,
        })
        try:
            self._proc.stdin.write((msg + "\n").encode())
        except Exception:
            pass

    async def _read_loop(self):
        """持续读取 stdout 的 JSON-RPC 响应"""
        buf = b""
        try:
            while self._proc and self._proc.stdout:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                # 按换行符分割，处理完整消息
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode())
                        rid = data.get("id")
                        if rid and rid in self._pending:
                            future = self._pending.pop(rid)
                            if "error" in data:
                                future.set_exception(
                                    Exception(data["error"].get("message", "mcp error")))
                            else:
                                future.set_result(data.get("result", {}))
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("[mcp:%s] 读取异常: %s", self.name, str(e))
