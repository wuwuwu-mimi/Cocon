from enum import Enum
from typing import TypedDict, List, Optional, Dict


class SubtaskStatus(str,Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"  # 依赖未满足

class Subtask(TypedDict):
    id: str
    description: str
    tool: str                     # 工具名，或 "none" 表示 LLM 直接处理
    args: dict
    depends_on: List[str]
    expected_output: str
    status: str                   # pending | running | done | failed
    result: Optional[dict]
    retry_count: int
    review_status: str            # pending | passed | blocked_human | retry
    review_score: float


class OrchestratorState(TypedDict):
    """LangGraph 全局状态"""
    # 任务基本信息
    task_id: str
    original_query: str

    # 任务规划
    plan: dict                    # {"subtasks": [...], "parallel_groups": [...]}
    subtask_map: Dict[str, Subtask]
    parallel_groups: List[List[str]]

    # 当前执行上下文
    current_subtask_id: str
    current_subtask_result: dict

    # 重规划
    replan_needed: bool
    new_subtasks: List[dict]

    # 人工审批
    human_interrupt: bool
    human_decision: Optional[dict]

    # 最终输出
    final_output: str
    status: str                   # planning|executing|waiting_human|done|failed