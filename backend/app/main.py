from __future__ import annotations

"""Agentic RAG 后端的 HTTP 入口。

这一层只负责请求校验、任务创建、限流检查和响应封装，具体业务逻辑交给
workflow、retriever、memory、task service 等模块。这样后续替换内部实现时，
前端和外部调用方的接口可以保持稳定。
"""

from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.agent.workflow import workflow
from app.rag.retriever import retriever
from app.services.events import stream_events
from app.services.memory import memory_service
from app.services.rate_limit import rate_limiter
from app.services.tasks import task_service
from app.tools.registry import tool_registry


app = FastAPI(title="Agentic RAG Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str = Field(default="demo")
    message: str


class IngestRequest(BaseModel):
    doc_id: str
    text: str
    source: str = "manual"


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


@app.post("/api/ingest")
def ingest(request: IngestRequest) -> dict:
    chunks = retriever.add_document(request.doc_id, request.text, source=request.source)
    return {"ok": True, "doc_id": request.doc_id, "chunks": chunks}


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
    return {
        "task_id": task.task_id,
        "session_id": state.session_id,
        "status": "cancelled" if state.cancelled else "completed",
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
