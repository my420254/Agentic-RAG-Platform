from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_api():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_tools_api_exposes_schema():
    response = client.get("/api/tools")

    assert response.status_code == 200
    body = response.json()
    assert body["tools"][0]["name"] == "policy_lookup"
    assert body["tools"][0]["input_schema"]["required"] == ["topic"]


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
