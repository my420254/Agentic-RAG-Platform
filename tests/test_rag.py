import asyncio

from app.agent.state import AgentState
from app.agent.workflow import workflow
from app.rag.chunker import split_text
from app.rag.retriever import InMemoryRetriever, tokenize
from app.services.tasks import task_service
from app.tools.registry import tool_registry


def test_split_text_uses_overlap():
    chunks = split_text("abcdef" * 100, max_chars=100, overlap=20)
    assert len(chunks) > 1
    assert chunks[0][-20:] == chunks[1][:20]


def test_retriever_returns_ranked_evidence():
    retriever = InMemoryRetriever()
    retriever.add_document("doc", "Redis 可以保存 Agent 的短期记忆和 checkpoint。")
    evidence = retriever.search("Redis Agent checkpoint")
    assert evidence
    assert evidence[0].score >= evidence[-1].score
    assert evidence[0].metadata["fusion"] == "rrf"


def test_tokenize_supports_chinese_bigrams():
    tokens = tokenize("限制RAG幻觉")
    assert "rag" in tokens
    assert "幻觉" in tokens


def test_hybrid_retriever_prefers_exact_business_terms():
    retriever = InMemoryRetriever()
    retriever.add_document("billing", "错误码 E1001 表示账单接口超时，需要重试。")
    retriever.add_document("general", "系统需要控制幻觉并返回引用证据。")

    evidence = retriever.search("E1001 账单 接口")

    assert evidence
    assert evidence[0].doc_id.startswith("billing")
    assert evidence[0].metadata["bm25_score"] > 0


def test_tool_registry_exposes_schema():
    tools = tool_registry.list_specs()
    assert tools[0]["name"] == "policy_lookup"
    assert "input_schema" in tools[0]


def test_workflow_marks_task_completed():
    task = task_service.create_task("unit-complete", "如何限制 RAG 幻觉？")
    state = AgentState(session_id=task.session_id, message=task.message, task_id=task.task_id)

    events = asyncio.run(_collect_events(state))
    stored = task_service.get_task(task.task_id)

    assert events[-1][0] == "answer"
    assert stored is not None
    assert stored.status == "completed"
    assert stored.events


def test_workflow_honors_cancelled_task():
    task = task_service.create_task("unit-cancel", "如何限制 RAG 幻觉？")
    task_service.cancel_task(task.task_id)
    state = AgentState(session_id=task.session_id, message=task.message, task_id=task.task_id)

    events = asyncio.run(_collect_events(state))
    stored = task_service.get_task(task.task_id)

    assert events[0][0] == "cancelled"
    assert stored is not None
    assert stored.status == "cancelled"


async def _collect_events(state: AgentState):
    events = []
    async for event, payload in workflow.run(state):
        events.append((event, payload))
    return events
