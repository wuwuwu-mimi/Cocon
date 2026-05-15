"""测试 Executor 占位符替换和类型保留"""
from orchestrator.nodes.executor import ExecutorAgent

# 用 __new__ 创建裸实例，跳过 __init__ 避免加载 LLM 客户端
_agent = object.__new__(ExecutorAgent)
def test_lookup_simple_path():
    ctx = {"sub_1": {"ok": True, "data": "hello world"}}
    val = ExecutorAgent._lookup_context("sub_1.data", ctx)
    assert val == "hello world"


def test_lookup_nested_path():
    ctx = {"sub_1": {"ok": True, "data": {"results": [{"title": "test"}]}}}
    val = ExecutorAgent._lookup_context("sub_1.data", ctx)
    assert "results" in val  # dict/list → JSON string


def test_lookup_missing_subtask():
    ctx = {}
    val = ExecutorAgent._lookup_context("sub_x.output", ctx)
    assert "未找到" in val


def test_lookup_int_preserved():
    ctx = {"sub_1": {"ok": True, "data": 42}}
    val = ExecutorAgent._lookup_context("sub_1.data", ctx)
    assert val == 42
    assert isinstance(val, int)


def test_lookup_bool_preserved():
    ctx = {"sub_1": {"ok": True, "data": True}}
    val = ExecutorAgent._lookup_context("sub_1.data", ctx)
    assert val is True


def test_lookup_float_preserved():
    ctx = {"sub_1": {"ok": True, "data": 3.14}}
    val = ExecutorAgent._lookup_context("sub_1.data", ctx)
    assert val == 3.14
    assert isinstance(val, float)


def test_lookup_non_existent_field():
    ctx = {"sub_1": {"ok": True, "data": {"name": "test"}}}
    val = ExecutorAgent._lookup_context("sub_1.data.age", ctx)
    assert "name" in val  # 找不到字段返回上级的 JSON


def test_replace_refs_str():
    ctx = {"sub_1": {"ok": True, "data": "result"}}
    val = ExecutorAgent._replace_refs(_agent, "{{sub_1.data}}", ctx)
    assert val == "result"


def test_replace_refs_dict():
    ctx = {"sub_1": {"ok": True, "data": "ok"}}
    val = ExecutorAgent._replace_refs(_agent, {"k": "{{sub_1.data}}"}, ctx)
    assert val == {"k": "ok"}


def test_replace_refs_list():
    ctx = {"sub_1": {"ok": True, "data": "v"}}
    val = ExecutorAgent._replace_refs(_agent, ["{{sub_1.data}}", "x"], ctx)
    assert val == ["v", "x"]


def test_replace_refs_no_match():
    val = ExecutorAgent._replace_refs(_agent, "plain text", {})
    assert val == "plain text"
