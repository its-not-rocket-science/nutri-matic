"""A small in-process sliding-window rate limiter for public,
unauthenticated endpoints (currently just `POST /api/auth/demo` — see
app/demo_protection.py).

Deliberately in-memory and per-process, not backed by Redis or any
shared store — this repo has no such dependency yet and a single-process
limiter is enough to stop casual/scripted abuse of a single backend
instance. If the backend is ever scaled to multiple processes or
instances behind a load balancer, each one enforces its own independent
budget rather than a combined one — see docs/rate-limiting.md before
assuming this alone is sufficient at that point; an edge/infra-level
control (reverse proxy, CDN, WAF) would be needed for a real shared
limit.
"""

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Records a hit for `key` unless it would exceed `limit` within
        the trailing `window_seconds`. Returns (allowed, retry_after_seconds)
        — retry_after is 0 when allowed, otherwise how long until the
        oldest hit in the window ages out."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
                return False, retry_after
            bucket.append(now)
            return True, 0

    def reset(self) -> None:
        """Test-only: clears all recorded hits."""
        with self._lock:
            self._buckets.clear()
