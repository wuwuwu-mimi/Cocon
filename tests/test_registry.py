"""测试 ToolRegistry ACL"""
import asyncio
from tools.registry import ToolRegistry


async def _dummy_tool():
    return {"result": "ok"}


def test_acl_permits_whitelisted_caller():
    reg = ToolRegistry()
    reg.register("test_tool", _dummy_tool, {}, acl=["executor"])
    result = asyncio.run(reg.call("test_tool", caller_id="executor"))
    assert result["ok"]


def test_acl_denies_non_whitelisted_caller():
    reg = ToolRegistry()
    reg.register("test_tool", _dummy_tool, {}, acl=["planner"])
    result = asyncio.run(reg.call("test_tool", caller_id="executor"))
    assert not result["ok"]
    assert "permission_denied" in result["error"]


def test_acl_none_allows_all():
    reg = ToolRegistry()
    reg.register("test_tool", _dummy_tool, {})  # no acl = anyone
    result = asyncio.run(reg.call("test_tool", caller_id="anyone"))
    assert result["ok"]


def test_unknown_tool():
    reg = ToolRegistry()
    result = asyncio.run(reg.call("nonexistent"))
    assert not result["ok"]
    assert "未知工具" in result["error"]
