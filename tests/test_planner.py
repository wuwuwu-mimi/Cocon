"""测试 Planner JSON 解析"""
from orchestrator.nodes.planner import PlannerAgent


def test_empty_plan():
    assert PlannerAgent.plan_to_subtask_map(None) == {}
    assert PlannerAgent.plan_to_subtask_map({}) == {}


def test_missing_subtasks_key():
    assert PlannerAgent.plan_to_subtask_map({"other": "data"}) == {}


def test_tasks_instead_of_subtasks():
    plan = {"tasks": [{"id": "s1", "description": "d", "tool": "web_search"}]}
    result = PlannerAgent.plan_to_subtask_map(plan)
    assert len(result) == 1
    assert result["s1"]["id"] == "s1"


def test_subtasks_as_dict():
    plan = {"subtasks": {"s1": {"id": "s1", "description": "d", "tool": "none"}}}
    result = PlannerAgent.plan_to_subtask_map(plan)
    assert len(result) == 1
    assert result["s1"]["tool"] == "none"


def test_missing_fields_get_defaults():
    plan = {"subtasks": [{"id": "s1"}]}
    result = PlannerAgent.plan_to_subtask_map(plan)
    assert result["s1"]["tool"] == "none"
    assert result["s1"]["description"] == ""
    assert result["s1"]["args"] == {}
    assert result["s1"]["depends_on"] == []
    assert result["s1"]["status"] == "pending"
    assert result["s1"]["retry_count"] == 0
    assert result["s1"]["review_score"] == 0.0


def test_skip_missing_id():
    plan = {"subtasks": [{"description": "no id here"}]}
    result = PlannerAgent.plan_to_subtask_map(plan)
    assert len(result) == 0


def test_normal_plan():
    plan = {
        "subtasks": [
            {"id": "s1", "description": "搜索", "tool": "web_search",
             "args": {"query": "test"}, "depends_on": [], "expected_output": "结果"},
            {"id": "s2", "description": "总结", "tool": "none",
             "args": {}, "depends_on": ["s1"], "expected_output": "汇总"},
        ]
    }
    result = PlannerAgent.plan_to_subtask_map(plan)
    assert len(result) == 2
    assert result["s1"]["tool"] == "web_search"
    assert result["s2"]["depends_on"] == ["s1"]
