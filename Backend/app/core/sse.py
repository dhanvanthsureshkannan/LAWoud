"""Server-Sent Events formatting helpers."""

import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    """Format one SSE frame: an ``event:`` line plus a JSON ``data:`` line.

    Multi-line JSON is impossible here since json.dumps with no indent never
    embeds a literal newline, but we still guard against it because a stray
    newline inside `data:` would silently truncate the frame per the SSE spec.
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    payload = payload.replace("\n", "\\n").replace("\r", "")
    return f"event: {event}\ndata: {payload}\n\n"


def sse_heartbeat() -> str:
    """A comment line — ignored by EventSource, keeps proxies/browsers from timing out."""
    return ": heartbeat\n\n"
