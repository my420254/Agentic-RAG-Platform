from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.state import AgentState
from app.agent.workflow import workflow
from app.rag.retriever import retriever
from app.services.events import stream_events
from app.services.memory import memory_service


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
    state = AgentState(session_id=request.session_id, message=request.message)
    async for _event, _payload in workflow.run(state):
        pass
    return {
        "session_id": state.session_id,
        "answer": state.answer,
        "citations": [item.__dict__ for item in state.evidence],
        "trace": state.trace,
    }


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    state = AgentState(session_id=request.session_id, message=request.message)

    async def events() -> AsyncIterator[tuple[str, dict]]:
        async for event, payload in workflow.run(state):
            yield event, {"session_id": state.session_id, **payload}

    return StreamingResponse(stream_events(events()), media_type="text/event-stream")
