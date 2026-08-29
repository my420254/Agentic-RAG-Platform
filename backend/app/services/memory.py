from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency in docs-only use
    redis = None


class MemoryService:
    """Redis 优先、内存兜底的会话记忆服务。"""

    def __init__(self) -> None:
        self._fallback: dict[str, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=20))
        self._client = None
        if redis is not None and os.getenv("REDIS_URL"):
            self._client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    def append_message(self, session_id: str, role: str, content: str) -> None:
        event = {"role": role, "content": content}
        if self._client is not None:
            try:
                key = f"agent:session:{session_id}:messages"
                self._client.rpush(key, json.dumps(event, ensure_ascii=False))
                self._client.ltrim(key, -20, -1)
                return
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        self._fallback[session_id].append(event)

    def recent_messages(self, session_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
        if self._client is not None:
            try:
                key = f"agent:session:{session_id}:messages"
                raw = self._client.lrange(key, -limit, -1)
                return [json.loads(item) for item in raw]
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        return list(self._fallback[session_id])[-limit:]

    def checkpoint_key(self, session_id: str) -> str:
        return f"agent:session:{session_id}:checkpoint"


memory_service = MemoryService()
