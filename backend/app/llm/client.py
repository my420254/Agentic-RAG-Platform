from __future__ import annotations

"""OpenAI-compatible LLM 客户端。

项目默认使用确定性模板回答，保证测试和本地演示稳定。设置 `RAG_USE_LLM=true`
后才会调用 OpenAI-compatible 接口。生产演示时优先访问本地 Qwen/vLLM；
如果本地模型不可达，并且配置了 DeepSeek API Key，则自动切到 DeepSeek。
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agent.state import Evidence


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class LLMEndpointConfig:
    name: str
    provider: str
    enabled: bool
    api_base: str
    api_key: str
    model: str
    timeout_seconds: int
    max_tokens: int
    send_chat_template_kwargs: bool
    send_thinking_param: bool
    enable_thinking: bool

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_base and self.model and self.api_key)

    def public_config(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "enabled": self.enabled,
            "configured": self.configured,
            "api_base": self.api_base,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "send_chat_template_kwargs": self.send_chat_template_kwargs,
            "send_thinking_param": self.send_thinking_param,
            "enable_thinking": self.enable_thinking,
        }


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    endpoints: tuple[LLMEndpointConfig, ...]

    @classmethod
    def from_env(cls) -> "LLMConfig":
        enabled = env_bool("RAG_USE_LLM")
        primary = LLMEndpointConfig(
            name="primary",
            provider=os.getenv("LLM_PROVIDER", "local_qwen_vllm"),
            enabled=enabled,
            api_base=os.getenv("LLM_API_BASE", "http://192.168.27.250:18003/v1").rstrip("/"),
            api_key=os.getenv("LLM_API_KEY", "EMPTY"),
            model=os.getenv("LLM_MODEL", "Qwen3.6-27B"),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "512")),
            send_chat_template_kwargs=env_bool("LLM_SEND_CHAT_TEMPLATE_KWARGS", True),
            send_thinking_param=env_bool("LLM_SEND_THINKING_PARAM"),
            enable_thinking=env_bool("LLM_ENABLE_THINKING"),
        )
        fallback = LLMEndpointConfig(
            name="fallback",
            provider=os.getenv("LLM_FALLBACK_PROVIDER", "deepseek"),
            enabled=enabled and env_bool("LLM_FALLBACK_ENABLED", True),
            api_base=os.getenv("LLM_FALLBACK_API_BASE", "https://api.deepseek.com").rstrip("/"),
            api_key=first_env("LLM_FALLBACK_API_KEY", "DEEPSEEK_API_KEY"),
            model=os.getenv("LLM_FALLBACK_MODEL", "deepseek-v4-flash"),
            timeout_seconds=int(os.getenv("LLM_FALLBACK_TIMEOUT_SECONDS", os.getenv("LLM_TIMEOUT_SECONDS", "45"))),
            max_tokens=int(os.getenv("LLM_FALLBACK_MAX_TOKENS", os.getenv("LLM_MAX_TOKENS", "512"))),
            send_chat_template_kwargs=env_bool("LLM_FALLBACK_SEND_CHAT_TEMPLATE_KWARGS"),
            send_thinking_param=env_bool("LLM_FALLBACK_SEND_THINKING_PARAM", True),
            enable_thinking=env_bool("LLM_FALLBACK_ENABLE_THINKING"),
        )
        return cls(enabled=enabled, endpoints=(primary, fallback))


class OpenAICompatibleLLM:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

    @property
    def primary(self) -> LLMEndpointConfig:
        return self.config.endpoints[0]

    def answer(self, *, question: str, evidence: list[Evidence], tool_result: dict | None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "skipped": True, "reason": "RAG_USE_LLM is not enabled"}

        attempts: list[dict[str, Any]] = []
        for endpoint in self.config.endpoints:
            if not endpoint.configured:
                attempts.append(
                    {
                        **endpoint.public_config(),
                        "ok": False,
                        "skipped": True,
                        "reason": "endpoint not configured",
                    }
                )
                continue

            result = self._answer_with_endpoint(
                endpoint,
                question=question,
                evidence=evidence,
                tool_result=tool_result,
            )
            attempts.append({key: value for key, value in result.items() if key != "answer"})
            if result.get("ok"):
                return {**result, "attempts": attempts}

        return {
            "ok": False,
            "error": "all llm endpoints failed",
            "attempts": attempts,
        }

    def status(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                **self.primary.public_config(),
                "reachable": False,
                "skipped": True,
                "endpoints": [endpoint.public_config() for endpoint in self.config.endpoints],
            }

        endpoint_statuses = [self._status_for_endpoint(endpoint) for endpoint in self.config.endpoints]
        active = next((item for item in endpoint_statuses if item.get("reachable")), endpoint_statuses[0])
        return {**active, "endpoints": endpoint_statuses}

    def _answer_with_endpoint(
        self,
        endpoint: LLMEndpointConfig,
        *,
        question: str,
        evidence: list[Evidence],
        tool_result: dict | None,
    ) -> dict[str, Any]:
        prompt = self._build_prompt(question=question, evidence=evidence, tool_result=tool_result)
        payload: dict[str, Any] = {
            "model": endpoint.model,
            "temperature": 0.2,
            "max_tokens": endpoint.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": "你是企业知识库问答助手。只能基于给定证据回答；证据不足时明确拒答；回答必须带引用编号。",
                },
                {"role": "user", "content": prompt},
            ],
        }
        if endpoint.send_chat_template_kwargs:
            payload["chat_template_kwargs"] = {"enable_thinking": endpoint.enable_thinking}
        if endpoint.send_thinking_param:
            payload["thinking"] = {"type": "enabled" if endpoint.enable_thinking else "disabled"}

        result = self._post_json(endpoint, "/chat/completions", payload)
        if not result.get("ok"):
            return result

        body = result["body"]
        answer = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not answer:
            return {**self._endpoint_result(endpoint), "ok": False, "error": "empty model response"}
        return {
            **self._endpoint_result(endpoint),
            "ok": True,
            "answer": answer,
            "usage": body.get("usage", {}),
            "latency_ms": result["latency_ms"],
        }

    def _status_for_endpoint(self, endpoint: LLMEndpointConfig) -> dict[str, Any]:
        public_config = endpoint.public_config()
        if not endpoint.enabled:
            return {**public_config, "reachable": False, "skipped": True, "reason": "endpoint disabled"}
        if not endpoint.configured:
            return {**public_config, "reachable": False, "skipped": True, "reason": "endpoint not configured"}

        result = self._get_json(endpoint, "/models")
        if not result.get("ok"):
            return result

        body = result["body"]
        models = [item.get("id") for item in body.get("data", []) if item.get("id")]
        return {
            **public_config,
            "reachable": True,
            "latency_ms": result["latency_ms"],
            "models": models,
        }

    def _post_json(self, endpoint: LLMEndpointConfig, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{endpoint.api_base}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {endpoint.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._open_json(endpoint, request)

    def _get_json(self, endpoint: LLMEndpointConfig, path: str) -> dict[str, Any]:
        request = Request(
            f"{endpoint.api_base}{path}",
            headers={"Authorization": f"Bearer {endpoint.api_key}"},
            method="GET",
        )
        return self._open_json(endpoint, request)

    def _open_json(self, endpoint: LLMEndpointConfig, request: Request) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=endpoint.timeout_seconds) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return {**self._endpoint_result(endpoint), "ok": True, "body": body, "latency_ms": latency_ms}
        except HTTPError as exc:
            return {**self._endpoint_result(endpoint), "ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {**self._endpoint_result(endpoint), "ok": False, "error": str(exc)}

    @staticmethod
    def _endpoint_result(endpoint: LLMEndpointConfig) -> dict[str, Any]:
        return {
            "endpoint": endpoint.name,
            "provider": endpoint.provider,
            "api_base": endpoint.api_base,
            "model": endpoint.model,
        }

    @staticmethod
    def _build_prompt(*, question: str, evidence: list[Evidence], tool_result: dict | None) -> str:
        evidence_block = "\n".join(
            f"[{index}] doc_id={item.doc_id} source={item.source}\n{item.text}"
            for index, item in enumerate(evidence, start=1)
        )
        tool_block = json.dumps(tool_result, ensure_ascii=False) if tool_result else "无"
        return (
            f"用户问题：{question}\n\n"
            f"检索证据：\n{evidence_block or '无'}\n\n"
            f"工具结果：{tool_block}\n\n"
            "请输出简洁中文答案，并在关键事实后标注引用编号，例如 [1]。"
        )


llm_client = OpenAICompatibleLLM()
