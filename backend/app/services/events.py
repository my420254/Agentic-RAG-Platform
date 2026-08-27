from __future__ import annotations

import json
from collections.abc import AsyncIterator


def sse_event(event: str, data: dict, *, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False)
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


async def stream_events(events: AsyncIterator[tuple[str, dict]]) -> AsyncIterator[str]:
    index = 0
    async for event, data in events:
        index += 1
        yield sse_event(event, data, event_id=str(index))
