from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Small in-process limiter for expensive job submission endpoints."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, *, now: float | None = None) -> tuple[bool, int, float]:
        current_time = time.monotonic() if now is None else now
        cutoff = current_time - self.window_seconds
        events = self._events[key]
        while events and events[0] <= cutoff:
            events.popleft()

        if len(events) >= limit:
            retry_after = max(0.0, self.window_seconds - (current_time - events[0]))
            return False, len(events), retry_after

        events.append(current_time)
        return True, len(events), 0.0
