from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.agent.state import AgentState
from app.rag.retriever import retriever
from app.services.memory import memory_service
from app.tools.registry import tool_registry


class AgentWorkflow:
    """Small workflow that mirrors a production LangGraph layout."""

    async def run(self, state: AgentState) -> AsyncIterator[tuple[str, dict]]:
        await self._understand(state)
        yield "understand", {"intent": state.intent, "query": state.rewritten_query}

        await self._retrieve(state)
        yield "retrieve", {"evidence_count": len(state.evidence)}

        await self._rerank(state)
        yield "rerank", {"evidence": [item.__dict__ for item in state.evidence]}

        await self._maybe_call_tool(state)
        if state.tool_result is not None:
            yield "tool", state.tool_result

        await self._answer(state)
        yield "answer", {"answer": state.answer, "citations": [item.doc_id for item in state.evidence]}

    async def _understand(self, state: AgentState) -> None:
        await asyncio.sleep(0)
        message = state.message.strip()
        state.intent = "policy" if "规则" in message or "策略" in message else "qa"
        state.rewritten_query = message.replace("？", "?")
        state.add_trace("understand", {"intent": state.intent})

    async def _retrieve(self, state: AgentState) -> None:
        await asyncio.sleep(0)
        state.evidence = retriever.search(state.rewritten_query, top_k=5)
        state.add_trace("retrieve", {"count": len(state.evidence)})

    async def _rerank(self, state: AgentState) -> None:
        await asyncio.sleep(0)
        state.evidence = sorted(
            state.evidence,
            key=lambda item: (item.score, -len(item.text)),
            reverse=True,
        )[:3]
        state.add_trace("rerank", {"selected": [item.doc_id for item in state.evidence]})

    async def _maybe_call_tool(self, state: AgentState) -> None:
        await asyncio.sleep(0)
        if "幻觉" not in state.message and "策略" not in state.message:
            return
        state.selected_tool = "policy_lookup"
        state.tool_result = tool_registry.call(
            "policy_lookup",
            {"topic": state.message},
            intent=state.intent,
        )
        state.add_trace("tool", {"name": state.selected_tool, "ok": state.tool_result.get("ok")})

    async def _answer(self, state: AgentState) -> None:
        await asyncio.sleep(0)
        memory_service.append_message(state.session_id, "user", state.message)
        if not state.evidence and not state.tool_result:
            state.answer = "当前知识库证据不足，建议补充文档或改写查询后再回答。"
        else:
            evidence_summary = "；".join(item.text[:80] for item in state.evidence)
            tool_summary = ""
            if state.tool_result and state.tool_result.get("ok"):
                tool_summary = f" 工具策略：{state.tool_result.get('policy')}"
            state.answer = (
                "基于当前证据，建议先保证检索质量，再约束生成："
                f"{evidence_summary}{tool_summary}"
            )
        memory_service.append_message(state.session_id, "assistant", state.answer)
        state.add_trace("answer", {"citations": [item.doc_id for item in state.evidence]})


workflow = AgentWorkflow()
