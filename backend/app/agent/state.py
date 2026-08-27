from __future__ import annotations

"""运行时共享状态对象。

workflow 会把同一个 AgentState 在各个节点之间传递。这个写法接近 LangGraph
的“状态驱动”风格，同时让当前仓库保持轻量，避免读者一开始就被框架细节淹没。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    """一条可被最终回答引用的检索证据。"""

    doc_id: str
    text: str
    score: float
    source: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """一次 Agentic RAG 任务的可变运行状态。"""

    session_id: str
    message: str
    task_id: str | None = None
    intent: str = "qa"
    rewritten_query: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    selected_tool: str | None = None
    tool_result: dict | None = None
    answer: str = ""
    cancelled: bool = False
    error: str | None = None
    trace: list[dict] = field(default_factory=list)

    def add_trace(self, node: str, payload: dict) -> None:
        # trace 使用 dict 列表，便于直接序列化到 API 返回、日志或后续观测系统。
        self.trace.append({"node": node, **payload})
