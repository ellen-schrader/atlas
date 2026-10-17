"""A sliding-window rate limit per user, shared by the HTTP API and the MCP server.

In-process, so it bounds one worker rather than the fleet — enough to stop a single
caller looping something that makes an outbound or paid request every time.
Multi-process (gunicorn -w N, or several Fly machines) multiplies the effective cap
by the process count; a fleet-wide limit wants a shared store (Redis).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class PerUserRateLimiter:
    """Sliding-window cap, keyed by user.

    `check` is called from several threads at once (FastAPI's threadpool, the MCP
    server's worker threads). Without the lock the read-modify-write races (two
    callers both see room and both append, defeating the cap) and the eviction
    rebuild can hit "dictionary changed size during iteration"; the lock makes each
    check atomic.

    `key` is required: a limiter that silently fell back to one shared bucket would
    let one user's burst lock out everyone else.
    """

    def __init__(
        self, max_events: int, window_seconds: float, error: Callable[[], Exception]
    ) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._error = error  # what to raise when the cap is hit
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < self.window]
            if len(events) >= self.max_events:
                self._events[key] = events
                raise self._error()
            events.append(now)
            self._events[key] = events
            # Don't let the map grow without bound as users come and go.
            if len(self._events) > 10_000:
                self._events = {
                    k: v for k, v in self._events.items() if v and now - v[-1] < self.window
                }
