from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    allowed_intents: set[str]
    handler: ToolHandler


def _policy_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error_code": "MISSING_TOPIC", "message": "topic is required"}
    return {
        "ok": True,
        "topic": topic,
        "policy": "证据不足时拒答；涉及实时状态时以工具或数据库为准；所有关键回答必须带 citation。",
    }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools = {
            "policy_lookup": ToolSpec(
                name="policy_lookup",
                description="查询 RAG/Agent 安全策略和业务规则",
                allowed_intents={"qa", "policy"},
                handler=_policy_lookup,
            )
        }

    def call(self, name: str, payload: dict[str, Any], *, intent: str) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "error_code": "UNKNOWN_TOOL", "message": f"unknown tool: {name}"}
        if intent not in spec.allowed_intents:
            return {"ok": False, "error_code": "INTENT_FORBIDDEN", "message": "tool not allowed for intent"}
        return spec.handler(payload)

    def names_for_intent(self, intent: str) -> list[str]:
        return [name for name, spec in self._tools.items() if intent in spec.allowed_intents]


tool_registry = ToolRegistry()
