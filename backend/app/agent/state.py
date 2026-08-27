from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Evidence:
    doc_id: str
    text: str
    score: float
    source: str = "local"


@dataclass
class AgentState:
    session_id: str
    message: str
    intent: str = "qa"
    rewritten_query: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    selected_tool: str | None = None
    tool_result: dict | None = None
    answer: str = ""
    trace: list[dict] = field(default_factory=list)

    def add_trace(self, node: str, payload: dict) -> None:
        self.trace.append({"node": node, **payload})
