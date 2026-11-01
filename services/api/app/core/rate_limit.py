"""Small process-local request limiter for single-instance deployments.

This is deliberately conservative: it is an abuse-control layer, not a
distributed quota system. Multi-instance production should place an
IP/user-aware limiter at the edge as well.
"""
from collections import defaultdict, deque
from threading import Lock
import time


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            events = self._events[key]
            cutoff = timestamp - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window_seconds - timestamp + 0.999))
                return False, retry_after
            events.append(timestamp)
            return True, 0

