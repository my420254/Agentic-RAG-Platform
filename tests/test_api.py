from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_api():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.headers["x-request-id"]


def test_llm_status_api_exposes_runtime_config():
    response = client.get("/api/llm/status")

    assert response.status_code == 200
    body = response.json()
    assert "enabled" in body
    assert "api_base" in body
    assert "model" in body


def test_runtime_status_api_reports_deployment_shape():
    response = client.get("/api/runtime/status", headers={"x-request-id": "req-test"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test"
    body = response.json()
    assert body["service"] == "agentic-rag-platform"
    assert body["api_port"] == 18080
    assert "documents" in body
    assert "llm" in body


def test_tools_api_exposes_schema():
    response = client.get("/api/tools")

    assert response.status_code == 200
    body = response.json()
    names = {item["name"] for item in body["tools"]}
    assert "policy_lookup" in names
    assert "ticket_status_lookup" in names


def test_document_and_retrieval_diagnostics_api():
    ingested = client.post(
        "/api/ingest",
        json={
            "doc_id": "api_diag",
            "text": "工单 INC-9999 表示检索服务超时，需要查看向量库和 reranker。",
            "source": "test",
        },
    )
    assert ingested.status_code == 200

    documents = client.get("/api/documents")
    assert documents.status_code == 200
    assert documents.json()["stats"]["documents"] >= 1

    retrieved = client.post(
        "/api/retrieve",
        json={"query": "INC-9999 检索服务超时", "top_k": 3},
    )
    assert retrieved.status_code == 200
    body = retrieved.json()
    assert body["fused"]
    assert body["bm25"]


def test_demo_load_api_is_idempotent_and_clear_keeps_demo_docs():
    first = client.post("/api/demo/load")
    second = client.post("/api/demo/load")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["stats"]["documents"] >= 3

    uploaded = client.post(
        "/api/ingest",
        json={
            "doc_id": "temporary_upload",
            "text": "这是一份用户临时上传的测试文档。",
            "source": "frontend_manual",
        },
    )
    assert uploaded.status_code == 200

    cleared = client.post("/api/documents/clear")
    assert cleared.status_code == 200

    documents = client.get("/api/documents").json()["documents"]
    doc_ids = {item["doc_id"] for item in documents}
    assert "temporary_upload" not in doc_ids
    assert "agent_harness" in doc_ids


def test_retrieval_eval_api():
    response = client.post(
        "/api/eval/retrieval",
        json={
            "top_k": 3,
            "cases": [
                {
                    "case_id": "api_eval",
                    "question": "Agent 短期记忆应该放在哪里？",
                    "expected_doc_ids": ["agent_memory"],
                    "tags": ["memory"],
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["hit_rate"] == 1.0


def test_task_api_supports_create_read_and_cancel():
    created = client.post(
        "/api/tasks",
        json={"session_id": "api-test", "message": "如何限制 RAG 幻觉？"},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    read = client.get(f"/api/tasks/{task_id}")
    assert read.status_code == 200
    assert read.json()["status"] == "pending"

    cancelled = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancel_requested"


def test_chat_api_returns_answer_and_trace():
    response = client.post(
        "/api/chat",
        json={"session_id": "api-chat", "message": "如何限制 RAG 幻觉？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["task_id"].startswith("task_")
    assert body["answer"]
    assert body["trace"]

    trace = client.get(f"/api/tasks/{body['task_id']}/trace")
    assert trace.status_code == 200
    assert trace.json()["summary"]["event_count"] > 0
