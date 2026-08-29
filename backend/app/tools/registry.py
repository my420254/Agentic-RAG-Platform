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


def _ticket_status_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    ticket_id = str(payload.get("ticket_id") or "").strip().upper()
    if not ticket_id:
        return {"ok": False, "error_code": "MISSING_TICKET_ID", "message": "缺少 ticket_id 参数"}
    demo_status = {
        "INC-1001": {
            "status": "retrying",
            "owner": "payment-platform",
            "summary": "账单接口超时，已启用指数退避重试。",
        },
        "INC-2002": {
            "status": "mitigated",
            "owner": "rag-platform",
            "summary": "向量库慢查询已通过热门 query 缓存缓解。",
        },
    }
    item = demo_status.get(ticket_id)
    if item is None:
        return {
            "ok": False,
            "error_code": "TICKET_NOT_FOUND",
            "message": f"未找到工单 {ticket_id}",
        }
    return {"ok": True, "ticket_id": ticket_id, **item}


class ToolRegistry:
    def __init__(self) -> None:
        # 新增业务工具时，在这里补 ToolSpec。所有工具必须经过统一 schema 和意图检查。
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
            ),
            "ticket_status_lookup": ToolSpec(
                name="ticket_status_lookup",
                description="查询演示工单状态，用于说明实时事实应通过工具而不是静态知识库获取",
                allowed_intents={"qa", "ticket"},
                handler=_ticket_status_lookup,
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "string",
                            "description": "工单编号，例如 INC-1001",
                        }
                    },
                    "required": ["ticket_id"],
                },
            ),
        }

    def call(self, name: str, payload: dict[str, Any], *, intent: str) -> dict[str, Any]:
        # 工具调用先检查工具是否存在，再检查当前意图是否允许调用。
        # 生产系统还应继续检查用户权限、租户边界、幂等 key 和超时策略。
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "error_code": "UNKNOWN_TOOL", "message": f"未知工具: {name}"}
        if intent not in spec.allowed_intents:
            return {"ok": False, "error_code": "INTENT_FORBIDDEN", "message": "当前意图不允许调用该工具"}
        schema_error = self._validate_payload(payload, spec.input_schema)
        if schema_error:
            return {"ok": False, "error_code": "SCHEMA_INVALID", "message": schema_error}
        return spec.handler(payload)

    @staticmethod
    def _validate_payload(payload: dict[str, Any], schema: dict[str, Any]) -> str:
        required = schema.get("required", [])
        for key in required:
            if key not in payload or payload.get(key) in {None, ""}:
                return f"缺少必填参数: {key}"
        properties = schema.get("properties", {})
        for key, spec in properties.items():
            if key not in payload:
                continue
            expected_type = spec.get("type")
            value = payload[key]
            if expected_type == "string" and not isinstance(value, str):
                return f"参数 {key} 必须是 string"
            if expected_type == "object" and not isinstance(value, dict):
                return f"参数 {key} 必须是 object"
        return ""

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
