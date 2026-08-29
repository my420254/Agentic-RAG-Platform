from __future__ import annotations

from app.services.memory import MemoryService
from app.services.rate_limit import RateLimiter
from app.services.tasks import TaskService


class BrokenRedis:
    def incr(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def expire(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def ttl(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def rpush(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def ltrim(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def lrange(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def set(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")

    def get(self, *_args, **_kwargs):  # noqa: ANN001
        raise ConnectionError("redis down")


def test_rate_limiter_falls_back_when_redis_connection_fails():
    limiter = RateLimiter()
    limiter._client = BrokenRedis()

    result = limiter.allow("demo", limit=2, window_seconds=60)

    assert result.allowed is True
    assert result.remaining == 1
    assert limiter._client is None


def test_memory_service_falls_back_when_redis_connection_fails():
    memory = MemoryService()
    memory._client = BrokenRedis()

    memory.append_message("s1", "user", "hello")

    assert memory._client is None
    assert memory.recent_messages("s1") == [{"role": "user", "content": "hello"}]


def test_task_service_falls_back_when_redis_connection_fails():
    tasks = TaskService()
    tasks._client = BrokenRedis()

    record = tasks.create_task("s1", "如何限制幻觉？")
    tasks.append_event(record.task_id, "understand", {"intent": "qa"})
    tasks.cancel_task(record.task_id)

    stored = tasks.get_task(record.task_id)
    assert tasks._client is None
    assert stored is not None
    assert stored.status == "cancel_requested"
    assert stored.events[0]["event"] == "understand"
    assert tasks.is_cancelled(record.task_id) is True
