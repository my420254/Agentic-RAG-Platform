from __future__ import annotations

"""Agentic RAG 后端的 HTTP 入口。

这一层只负责请求校验、任务创建、限流检查和响应封装，具体业务逻辑交给
workflow、retriever、memory、task service 等模块。这样后续替换内部实现时，
前端和外部调用方的接口可以保持稳定。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.agent.workflow import workflow
from app.llm.client import llm_client
from app.rag.evaluator import RetrievalEvalCase, run_retrieval_eval
from app.rag.retriever import retriever
from app.services.demo_knowledge import load_demo_knowledge
from app.services.events import stream_events
from app.services.memory import memory_service
from app.services.rate_limit import rate_limiter
from app.services.tasks import task_service
from app.services.trace import summarize_events
from app.tools.registry import tool_registry


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if os.getenv("AUTO_LOAD_DEMO_KNOWLEDGE", "true").lower() in {"1", "true", "yes"}:
        load_demo_knowledge(retriever)
    yield


allowed_origins = cors_origins()
app = FastAPI(title="Agentic RAG Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials="*" not in allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):  # noqa: ANN001
    request_id = request.headers.get("x-request-id") or uuid4().hex
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


class ChatRequest(BaseModel):
    session_id: str = Field(default="demo")
    message: str


class IngestRequest(BaseModel):
    doc_id: str
    text: str
    source: str = "manual"


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievalEvalRequest(BaseModel):
    top_k: int = Field(default=5, ge=1, le=20)
    cases: list[dict] = Field(default_factory=list)


class TaskSubmitRequest(BaseModel):
    session_id: str = Field(default="demo")
    message: str


class ToolCallRequest(BaseModel):
    intent: str = "qa"
    payload: dict = Field(default_factory=dict)


def enforce_rate_limit(session_id: str) -> dict:
    # 当前按 session_id 做限流。生产系统通常会按 tenant_id、user_id、API key、
    # IP、模型档位等维度组合限流。
    result = rate_limiter.allow(f"session:{session_id}", limit=120, window_seconds=60)
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "rate limit exceeded",
                "limit": result.limit,
                "reset_seconds": result.reset_seconds,
            },
        )
    return {
        "limit": result.limit,
        "remaining": result.remaining,
        "reset_seconds": result.reset_seconds,
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "agentic-rag-platform"}


@app.get("/api/llm/status")
def llm_status() -> dict:
    return llm_client.status()


@app.get("/api/runtime/status")
def runtime_status() -> dict:
    return {
        "service": "agentic-rag-platform",
        "app_env": os.getenv("APP_ENV", "development"),
        "api_port": int(os.getenv("APP_API_PORT", "18080")),
        "cors_origins": allowed_origins,
        "auto_load_demo_knowledge": os.getenv("AUTO_LOAD_DEMO_KNOWLEDGE", "true").lower()
        in {"1", "true", "yes"},
        "documents": retriever.stats(),
        "llm": llm_client.status(),
    }


@app.post("/api/ingest")
def ingest(request: IngestRequest) -> dict:
    chunks = retriever.add_document(request.doc_id, request.text, source=request.source)
    return {"ok": True, "doc_id": request.doc_id, "chunks": chunks}


@app.post("/api/demo/load")
def load_demo_documents() -> dict:
    loaded = load_demo_knowledge(retriever)
    return {
        "ok": True,
        "loaded": [item.__dict__ for item in loaded],
        "stats": retriever.stats(),
    }


@app.get("/api/documents")
def list_documents() -> dict:
    return {"stats": retriever.stats(), "documents": retriever.list_documents()}


@app.post("/api/documents/clear")
def clear_user_documents() -> dict:
    removed_chunks = retriever.clear_user_documents()
    return {"ok": True, "removed_chunks": removed_chunks, "stats": retriever.stats()}


@app.post("/api/retrieve")
def retrieve(request: RetrieveRequest) -> dict:
    return retriever.diagnose(request.query, top_k=request.top_k)


@app.post("/api/eval/retrieval")
def retrieval_eval(request: RetrievalEvalRequest) -> dict:
    if request.cases:
        cases = [RetrievalEvalCase.from_dict(item) for item in request.cases]
    else:
        cases = [
            RetrievalEvalCase(
                case_id="rag_hallucination",
                question="RAG 系统如何减少幻觉并保证引用证据？",
                expected_doc_ids=["rag_handbook"],
                tags=["hallucination", "citation"],
            ),
            RetrievalEvalCase(
                case_id="agent_memory",
                question="Agent 的短期记忆和 checkpoint 应该放在哪里？",
                expected_doc_ids=["agent_memory"],
                tags=["memory", "redis"],
            ),
        ]
    return run_retrieval_eval(retriever, cases, top_k=request.top_k)


@app.get("/api/sessions/{session_id}/memory")
def read_memory(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "checkpoint_key": memory_service.checkpoint_key(session_id),
        "messages": memory_service.recent_messages(session_id),
    }


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    # 同步路径：一次性跑完整个 workflow，直接返回最终状态，适合测试和简单客户端。
    rate_limit = enforce_rate_limit(request.session_id)
    task = task_service.create_task(request.session_id, request.message)
    state = AgentState(session_id=request.session_id, message=request.message, task_id=task.task_id)
    async for _event, _payload in workflow.run(state):
        pass
    if state.error:
        status = "failed"
    elif state.cancelled:
        status = "cancelled"
    else:
        status = "completed"
    return {
        "task_id": task.task_id,
        "session_id": state.session_id,
        "status": status,
        "answer": state.answer,
        "citations": [item.__dict__ for item in state.evidence],
        "trace": state.trace,
        "rate_limit": rate_limit,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    # 流式路径：把每个 workflow 节点都作为 SSE 事件返回，前端用它渲染中间状态。
    enforce_rate_limit(request.session_id)
    task = task_service.create_task(request.session_id, request.message)
    state = AgentState(session_id=request.session_id, message=request.message, task_id=task.task_id)

    async def events() -> AsyncIterator[tuple[str, dict]]:
        yield "task_created", {
            "session_id": state.session_id,
            "task_id": task.task_id,
            "status": task.status,
        }
        async for event, payload in workflow.run(state):
            yield event, {"session_id": state.session_id, "task_id": task.task_id, **payload}

    return StreamingResponse(stream_events(events()), media_type="text/event-stream")


@app.post("/api/tasks")
def create_task(request: TaskSubmitRequest) -> dict:
    # 异步风格路径：先创建任务，再让客户端订阅事件。
    # 后续接 Kafka 或 Redis Stream 时，可以沿用这个 API 形态。
    rate_limit = enforce_rate_limit(request.session_id)
    task = task_service.create_task(request.session_id, request.message)
    return {**task.__dict__, "rate_limit": rate_limit}


@app.get("/api/tasks/{task_id}")
def read_task(task_id: str) -> dict:
    task = task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task.__dict__


@app.get("/api/tasks/{task_id}/trace")
def read_task_trace(task_id: str) -> dict:
    task = task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task_id": task_id,
        "summary": summarize_events(task.events),
        "events": task.events,
    }


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    # 取消请求写入 TaskService，由 workflow 在节点边界检查。
    # 这样不会为了“立刻停止”而粗暴杀线程或杀进程。
    task = task_service.cancel_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True, "task_id": task_id, "status": task.status}


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str) -> StreamingResponse:
    task = task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    state = AgentState(session_id=task.session_id, message=task.message, task_id=task.task_id)

    async def events() -> AsyncIterator[tuple[str, dict]]:
        yield "task_started", {
            "session_id": task.session_id,
            "task_id": task.task_id,
            "status": task.status,
        }
        async for event, payload in workflow.run(state):
            yield event, {"session_id": task.session_id, "task_id": task.task_id, **payload}

    return StreamingResponse(stream_events(events()), media_type="text/event-stream")


@app.get("/api/tools")
def list_tools() -> dict:
    return {"tools": tool_registry.list_specs()}


@app.post("/api/tools/{tool_name}/call")
def call_tool(tool_name: str, request: ToolCallRequest) -> dict:
    return tool_registry.call(tool_name, request.payload, intent=request.intent)
