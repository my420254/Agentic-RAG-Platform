from __future__ import annotations

"""请求限流服务。

当前实现固定窗口限流：有 Redis 时用 Redis 计数，没有 Redis 时用进程内队列兜底。
这个模块先解决“限流放在哪里、返回什么信息”的工程边界，后续可以替换成滑动窗口、
令牌桶或 API Gateway 限流。
"""

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import RLock

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class RateLimiter:
    """Redis 优先、内存兜底的固定窗口限流器。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._fallback: dict[str, deque[float]] = defaultdict(deque)
        self._client = None
        if redis is not None and os.getenv("REDIS_URL"):
            self._client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    def allow(self, subject: str, *, limit: int = 120, window_seconds: int = 60) -> RateLimitResult:
        # subject 可以是 session、用户、租户、API key 或模型端点。
        if self._client is not None:
            try:
                return self._allow_redis(subject, limit=limit, window_seconds=window_seconds)
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        return self._allow_memory(subject, limit=limit, window_seconds=window_seconds)

    def _allow_redis(self, subject: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        # Redis 路径使用 INCR + EXPIRE，是最常见的固定窗口限流实现。
        window = int(time.time() // window_seconds)
        key = f"agent:rate:{subject}:{window}"
        count = int(self._client.incr(key))
        if count == 1:
            self._client.expire(key, window_seconds)
        remaining = max(limit - count, 0)
        reset = self._client.ttl(key)
        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=remaining,
            reset_seconds=reset if reset > 0 else window_seconds,
        )

    def _allow_memory(self, subject: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        # 内存兜底只适合本地 demo；多进程或多实例部署时必须换成 Redis/API Gateway。
        now = time.time()
        with self._lock:
            events = self._fallback[subject]
            while events and now - events[0] >= window_seconds:
                events.popleft()
            allowed = len(events) < limit
            if allowed:
                events.append(now)
            reset = int(max(window_seconds - (now - events[0]), 0)) if events else window_seconds
            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=max(limit - len(events), 0),
                reset_seconds=reset,
            )


rate_limiter = RateLimiter()
