from __future__ import annotations

"""工具注册中心。

所有可被 Agent 调用的外部能力都先注册成 ToolSpec，再通过 ToolRegistry 统一调用。
这样可以集中处理 schema、意图白名单、参数校验和结构化错误，避免模型直接调用任意函数。
"""

from dataclasses import dataclass, field
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的公开描述和内部处理函数。"""

    name: str
    description: str
    allowed_intents: set[str]
    handler: ToolHandler
    input_schema: dict[str, Any] = field(default_factory=dict)


def _policy_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error_code": "MISSING_TOPIC", "message": "缺少 topic 参数"}
    return {
        "ok": True,
        "topic": topic,
        "policy": "证据不足时拒答；涉及实时状态时以工具或数据库为准；所有关键回答必须带 citation。",
    }


class ToolRegistry:
    def __init__(self) -> None:
        # 当前只放一个示例工具。新增业务工具时，在这里补 ToolSpec 即可。
        self._tools = {
            "policy_lookup": ToolSpec(
                name="policy_lookup",
                description="查询 RAG/Agent 安全策略和业务规则",
                allowed_intents={"qa", "policy"},
                handler=_policy_lookup,
                input_schema={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "需要查询的策略主题或用户问题",
                        }
                    },
                    "required": ["topic"],
                },
            )
        }

    def call(self, name: str, payload: dict[str, Any], *, intent: str) -> dict[str, Any]:
        # 工具调用先检查工具是否存在，再检查当前意图是否允许调用。
        # 生产系统还应继续检查用户权限、租户边界、幂等 key 和超时策略。
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "error_code": "UNKNOWN_TOOL", "message": f"未知工具: {name}"}
        if intent not in spec.allowed_intents:
            return {"ok": False, "error_code": "INTENT_FORBIDDEN", "message": "当前意图不允许调用该工具"}
        return spec.handler(payload)

    def names_for_intent(self, intent: str) -> list[str]:
        return [name for name, spec in self._tools.items() if intent in spec.allowed_intents]

    def list_specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "allowed_intents": sorted(spec.allowed_intents),
                "input_schema": spec.input_schema,
            }
            for spec in self._tools.values()
        ]


tool_registry = ToolRegistry()
