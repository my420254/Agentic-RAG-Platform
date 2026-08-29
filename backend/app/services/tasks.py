from __future__ import annotations

"""任务状态与取消服务。

Agent 任务通常比普通 HTTP 请求更长，因此需要 task_id、任务状态、节点事件和取消标记。
有 Redis 时写 Redis，没有 Redis 时自动退回内存，保证本地 demo 可以直接运行。
"""

import json
import os
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

try:
    import redis
except ImportError:  # pragma: no cover - optional dependency
    redis = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    task_id: str
    session_id: str
    message: str
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


class TaskService:
    """Redis 优先、内存兜底的任务状态存储。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._fallback: dict[str, TaskRecord] = {}
        self._client = None
        if redis is not None and os.getenv("REDIS_URL"):
            self._client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    def create_task(self, session_id: str, message: str) -> TaskRecord:
        # task_id 保持较短，便于 UI 展示；随机空间足够支撑 demo 和控制面标识。
        record = TaskRecord(
            task_id=f"task_{uuid4().hex[:16]}",
            session_id=session_id,
            message=message,
        )
        self._save(record)
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        # Redis 中任务元信息和事件列表分开存，这样裁剪事件列表时不用重写整个任务记录。
        if self._client is not None:
            try:
                raw = self._client.get(self._task_key(task_id))
                if not raw:
                    return None
                data = json.loads(raw)
                events = self._client.lrange(self._events_key(task_id), -100, -1)
                data["events"] = [json.loads(item) for item in events]
                return TaskRecord(**data)
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        with self._lock:
            return self._fallback.get(task_id)

    def update_status(self, task_id: str, status: str, *, error: str | None = None) -> TaskRecord | None:
        record = self.get_task(task_id)
        if record is None:
            return None
        record.status = status
        record.error = error
        record.updated_at = utc_now()
        self._save(record)
        return record

    def cancel_task(self, task_id: str) -> TaskRecord | None:
        # 取消请求不等于马上停止。workflow 会在下一个安全节点边界看到这个标记。
        record = self.update_status(task_id, "cancel_requested")
        if record is None:
            return None
        if self._client is not None:
            try:
                self._client.set(self._cancel_key(task_id), "1", ex=3600)
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        return record

    def is_cancelled(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        if self._client is not None:
            try:
                if self._client.get(self._cancel_key(task_id)):
                    return True
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        record = self.get_task(task_id)
        return record is not None and record.status in {"cancel_requested", "cancelled"}

    def append_event(self, task_id: str | None, event: str, payload: dict[str, Any]) -> None:
        # demo 保留最近 100 个事件即可支撑 UI trace 和调试。
        # 生产系统可以把同一份事件继续写入 Kafka、Langfuse 或日志平台。
        if not task_id:
            return
        item = {
            "event": event,
            "payload": payload,
            "created_at": utc_now(),
        }
        if self._client is not None:
            try:
                key = self._events_key(task_id)
                self._client.rpush(key, json.dumps(item, ensure_ascii=False))
                self._client.ltrim(key, -100, -1)
                return
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        with self._lock:
            record = self._fallback.get(task_id)
            if record is None:
                return
            events = deque(record.events, maxlen=100)
            events.append(item)
            record.events = list(events)
            record.updated_at = utc_now()

    def _save(self, record: TaskRecord) -> None:
        if self._client is not None:
            try:
                data = asdict(record)
                data["events"] = []
                self._client.set(self._task_key(record.task_id), json.dumps(data, ensure_ascii=False), ex=86400)
                return
            except Exception:  # pragma: no cover - exercised with fake redis in tests
                self._client = None
        with self._lock:
            self._fallback[record.task_id] = record

    @staticmethod
    def _task_key(task_id: str) -> str:
        return f"agent:task:{task_id}:state"

    @staticmethod
    def _events_key(task_id: str) -> str:
        return f"agent:task:{task_id}:events"

    @staticmethod
    def _cancel_key(task_id: str) -> str:
        return f"agent:task:{task_id}:cancel"


task_service = TaskService()
