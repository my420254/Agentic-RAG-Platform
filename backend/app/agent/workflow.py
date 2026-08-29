from __future__ import annotations

"""Agentic RAG 任务编排流程。

这个文件是项目的控制层：明确节点顺序、输出可观测事件，并在节点之间检查取消。
整体结构接近 LangGraph StateGraph，但当前版本不强制依赖 LangGraph，便于项目开箱运行。
"""

import asyncio
from collections.abc import AsyncIterator
import json

from app.agent.state import AgentState
from app.llm.client import llm_client
from app.rag.quality import assess_evidence
from app.rag.retriever import retriever
from app.services.memory import memory_service
from app.services.tasks import task_service
from app.tools.registry import tool_registry


class AgentWorkflow:
    """一个接近生产 LangGraph 分层的轻量 workflow。"""

    async def run(self, state: AgentState) -> AsyncIterator[tuple[str, dict]]:
        # 每一次 yield 都是外部可见的节点事件。
        # FastAPI 会把这些事件转成 SSE，TaskService 会把事件保存下来便于回看。
        try:
            if self._is_cancelled(state):
                yield self._cancel(state)
                return
            if state.task_id:
                task_service.update_status(state.task_id, "running")

            await self._understand(state)
            yield self._event(state, "understand", {"intent": state.intent, "query": state.rewritten_query})
            if self._is_cancelled(state):
                yield self._cancel(state)
                return

            await self._retrieve(state)
            yield self._event(state, "retrieve", {"evidence_count": len(state.evidence)})
            if self._is_cancelled(state):
                yield self._cancel(state)
                return

            await self._rerank(state)
            yield self._event(state, "rerank", {"evidence": [item.__dict__ for item in state.evidence]})
            if self._is_cancelled(state):
                yield self._cancel(state)
                return

            await self._quality_gate(state)
            yield self._event(state, "quality", state.quality)
            if self._is_cancelled(state):
                yield self._cancel(state)
                return

            await self._maybe_call_tool(state)
            if state.tool_result is not None:
                yield self._event(state, "tool", state.tool_result)
            if self._is_cancelled(state):
                yield self._cancel(state)
                return

            await self._answer(state)
            llm_payload = self._latest_trace_payload(state, "llm")
            if llm_payload is not None:
                yield self._event(state, "llm", llm_payload)
            yield self._event(state, "answer", {"answer": state.answer, "citations": [item.doc_id for item in state.evidence]})
            if state.task_id:
                task_service.update_status(state.task_id, "completed")
        except Exception as exc:  # pragma: no cover - defensive runtime path
            state.error = str(exc)
            state.answer = "任务执行失败，已记录错误。"
            payload = {"task_id": state.task_id, "status": "failed", "error": state.error}
            state.add_trace("error", payload)
            if state.task_id:
                task_service.update_status(state.task_id, "failed", error=state.error)
                task_service.append_event(state.task_id, "error", payload)
            yield "error", payload

    async def _understand(self, state: AgentState) -> None:
        # 生产系统里这里可以接 LLM 或意图分类器。
        # 当前项目保持确定性，便于本地运行和单元测试稳定。
        await asyncio.sleep(0)
        message = state.message.strip()
        if "工单" in message or "INC-" in message.upper():
            state.intent = "ticket"
        elif "规则" in message or "策略" in message:
            state.intent = "policy"
        else:
            state.intent = "qa"
        state.rewritten_query = message.replace("？", "?")
        state.add_trace("understand", {"intent": state.intent})

    async def _retrieve(self, state: AgentState) -> None:
        # 召回和重排分开，方便定位是“没召回到”还是“召回了但排序不对”。
        await asyncio.sleep(0)
        state.evidence = retriever.search(state.rewritten_query, top_k=5)
        state.add_trace("retrieve", {"count": len(state.evidence)})

    async def _rerank(self, state: AgentState) -> None:
        # retriever 内部已经完成 BM25-style 和向量相似度的 RRF 融合。
        # 这里再控制 workflow 层允许进入 prompt/回答阶段的证据数量。
        await asyncio.sleep(0)
        state.evidence = sorted(
            state.evidence,
            key=lambda item: (item.score, -len(item.text)),
            reverse=True,
        )[:3]
        state.add_trace("rerank", {"selected": [item.doc_id for item in state.evidence]})

    async def _quality_gate(self, state: AgentState) -> None:
        # 证据质量门控单独成节点，便于后续用评测集调阈值。
        await asyncio.sleep(0)
        quality = assess_evidence(state.evidence)
        state.quality = quality.to_dict()
        state.add_trace("quality", state.quality)

    async def _maybe_call_tool(self, state: AgentState) -> None:
        # 当前工具选择规则故意保持简单。
        # 关键点是所有工具调用必须经过 ToolRegistry，不能让模型直接调用任意 Python 函数。
        await asyncio.sleep(0)
        if state.intent == "ticket":
            ticket_id = self._extract_ticket_id(state.message)
            state.selected_tool = "ticket_status_lookup"
            state.tool_result = tool_registry.call(
                "ticket_status_lookup",
                {"ticket_id": ticket_id},
                intent=state.intent,
            )
            state.add_trace("tool", {"name": state.selected_tool, "ok": state.tool_result.get("ok")})
            return
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
        # 回答节点会同时写入用户消息和助手消息，memory 接口才能看到多轮会话状态。
        await asyncio.sleep(0)
        memory_service.append_message(state.session_id, "user", state.message)
        if not state.quality.get("enough") and not state.tool_result:
            state.answer = "当前知识库证据不足，建议补充文档或改写查询后再回答。"
        else:
            model_answer = await asyncio.to_thread(
                llm_client.answer,
                question=state.message,
                evidence=state.evidence,
                tool_result=state.tool_result,
            )
            if model_answer.get("ok"):
                state.answer = str(model_answer["answer"])
                state.add_trace(
                    "llm",
                    {
                        "mode": "openai_compatible",
                        "endpoint": model_answer.get("endpoint"),
                        "provider": model_answer.get("provider"),
                        "api_base": model_answer.get("api_base"),
                        "model": model_answer.get("model"),
                        "usage": model_answer.get("usage", {}),
                        "latency_ms": model_answer.get("latency_ms"),
                        "attempts": model_answer.get("attempts", []),
                    },
                )
            else:
                evidence_summary = "\n".join(
                    f"{index}. {item.text.strip()} [{index}]"
                    for index, item in enumerate(state.evidence, start=1)
                )
                tool_summary = ""
                if state.tool_result and state.tool_result.get("ok"):
                    if state.selected_tool == "policy_lookup":
                        tool_summary = f"\n策略约束：{state.tool_result.get('policy')}"
                    else:
                        compact_tool = json.dumps(state.tool_result, ensure_ascii=False)
                        tool_summary = f"\n实时工具结果：{compact_tool}"
                state.answer = (
                    "基于当前证据，建议按以下方式处理：\n"
                    f"{evidence_summary}{tool_summary}"
                )
                state.add_trace("llm", {"mode": "template_fallback", **model_answer})
        memory_service.append_message(state.session_id, "assistant", state.answer)
        state.add_trace("answer", {"citations": [item.doc_id for item in state.evidence]})

    @staticmethod
    def _extract_ticket_id(message: str) -> str:
        normalized = message.upper()
        for token in normalized.replace("，", " ").replace("。", " ").split():
            if token.startswith("INC-"):
                return token.strip(" ?")
        return ""

    def _is_cancelled(self, state: AgentState) -> bool:
        # 取消只在安全节点边界检查。
        # 如果后续接入长时间阻塞工具，需要配 timeout、worker 或子进程隔离。
        return task_service.is_cancelled(state.task_id)

    def _cancel(self, state: AgentState) -> tuple[str, dict]:
        state.cancelled = True
        state.answer = "任务已取消。"
        payload = {"task_id": state.task_id, "status": "cancelled"}
        state.add_trace("cancelled", payload)
        if state.task_id:
            task_service.update_status(state.task_id, "cancelled")
            task_service.append_event(state.task_id, "cancelled", payload)
        return "cancelled", payload

    def _event(self, state: AgentState, event: str, payload: dict) -> tuple[str, dict]:
        if state.task_id:
            task_service.append_event(state.task_id, event, payload)
        return event, payload

    @staticmethod
    def _latest_trace_payload(state: AgentState, node: str) -> dict | None:
        for item in reversed(state.trace):
            if item.get("node") == node:
                return {key: value for key, value in item.items() if key != "node"}
        return None


workflow = AgentWorkflow()
