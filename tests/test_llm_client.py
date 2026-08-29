from __future__ import annotations

import json

from app.agent.state import Evidence
from app.llm.client import LLMConfig, LLMEndpointConfig, OpenAICompatibleLLM


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_qwen_payload_includes_thinking_and_token_controls(monkeypatch):
    captured: dict = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["timeout"] = timeout
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "choices": [{"message": {"content": "基于证据回答。[1]"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )

    monkeypatch.setattr("app.llm.client.urlopen", fake_urlopen)
    client = OpenAICompatibleLLM(
        LLMConfig(
            enabled=True,
            endpoints=(
                LLMEndpointConfig(
                    name="primary",
                    provider="local_qwen_vllm",
                    enabled=True,
                    api_base="http://qwen.local/v1",
                    api_key="test-key",
                    model="Qwen3.6-27B",
                    timeout_seconds=3,
                    max_tokens=128,
                    send_chat_template_kwargs=True,
                    send_thinking_param=False,
                    enable_thinking=False,
                ),
            ),
        )
    )

    result = client.answer(
        question="如何减少幻觉？",
        evidence=[
            Evidence(
                doc_id="doc:0",
                text="证据不足时拒答，并强制引用。",
                source="test",
                score=1.0,
            )
        ],
        tool_result=None,
    )

    assert result["ok"] is True
    assert captured["timeout"] == 3
    assert captured["url"] == "http://qwen.local/v1/chat/completions"
    assert captured["payload"]["model"] == "Qwen3.6-27B"
    assert captured["payload"]["max_tokens"] == 128
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}


def test_fallback_endpoint_is_used_after_primary_failure(monkeypatch):
    calls: list[dict] = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        calls.append({"url": request.full_url, "timeout": timeout, "payload": payload})
        if request.full_url.startswith("http://qwen.local"):
            raise OSError("local qwen down")
        return FakeResponse(
            {
                "choices": [{"message": {"content": "已切换 DeepSeek 回答。[1]"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            }
        )

    monkeypatch.setattr("app.llm.client.urlopen", fake_urlopen)
    client = OpenAICompatibleLLM(
        LLMConfig(
            enabled=True,
            endpoints=(
                LLMEndpointConfig(
                    name="primary",
                    provider="local_qwen_vllm",
                    enabled=True,
                    api_base="http://qwen.local/v1",
                    api_key="qwen-key",
                    model="Qwen3.6-27B",
                    timeout_seconds=1,
                    max_tokens=128,
                    send_chat_template_kwargs=True,
                    send_thinking_param=False,
                    enable_thinking=False,
                ),
                LLMEndpointConfig(
                    name="fallback",
                    provider="deepseek",
                    enabled=True,
                    api_base="https://api.deepseek.com",
                    api_key="deepseek-key",
                    model="deepseek-v4-flash",
                    timeout_seconds=2,
                    max_tokens=128,
                    send_chat_template_kwargs=False,
                    send_thinking_param=True,
                    enable_thinking=False,
                ),
            ),
        )
    )

    result = client.answer(
        question="如何减少幻觉？",
        evidence=[
            Evidence(
                doc_id="doc:0",
                text="证据不足时拒答，并强制引用。",
                source="test",
                score=1.0,
            )
        ],
        tool_result=None,
    )

    assert result["ok"] is True
    assert result["provider"] == "deepseek"
    assert result["endpoint"] == "fallback"
    assert len(calls) == 2
    assert calls[0]["url"] == "http://qwen.local/v1/chat/completions"
    assert calls[1]["url"] == "https://api.deepseek.com/chat/completions"
    assert "chat_template_kwargs" not in calls[1]["payload"]
    assert calls[1]["payload"]["thinking"] == {"type": "disabled"}


def test_disabled_llm_status_does_not_probe_network():
    client = OpenAICompatibleLLM(
        LLMConfig(
            enabled=False,
            endpoints=(
                LLMEndpointConfig(
                    name="primary",
                    provider="local_qwen_vllm",
                    enabled=False,
                    api_base="http://qwen.local/v1",
                    api_key="test-key",
                    model="Qwen3.6-27B",
                    timeout_seconds=3,
                    max_tokens=128,
                    send_chat_template_kwargs=True,
                    send_thinking_param=False,
                    enable_thinking=False,
                ),
            ),
        )
    )

    status = client.status()

    assert status["enabled"] is False
    assert status["skipped"] is True
    assert status["reachable"] is False
