from __future__ import annotations

"""Trace 导出服务。

TaskService 保存的是运行时事件；TraceService 把这些事件转换成便于面试展示、
问题复盘和故障定位的 summary。
"""

from collections import Counter
from typing import Any


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    names = [str(item.get("event", "")) for item in events]
    counter = Counter(names)
    failed = [item for item in events if item.get("event") == "error"]
    cancelled = any(item.get("event") == "cancelled" for item in events)
    return {
        "event_count": len(events),
        "node_counts": dict(counter),
        "has_error": bool(failed),
        "cancelled": cancelled,
        "final_event": names[-1] if names else "",
    }
