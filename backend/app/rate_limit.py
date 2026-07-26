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
from collections import OrderedDict, deque

# Caps total memory regardless of how many distinct keys show up — a
# flood of one-off keys (spoofed/enumerated source IPs, each hit once)
# would otherwise grow `_buckets` forever, since a key only gets pruned
# when it's seen *again*. Least-recently-used keys are evicted once this
# cap is hit; that's a bounded-memory guarantee, not a promise that every
# key's history survives indefinitely under sustained attack. Found by
# an automated PR review, not manually — a real gap, not hypothetical.
DEFAULT_MAX_TRACKED_KEYS = 10_000


class SlidingWindowRateLimiter:
    def __init__(self, max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS) -> None:
        self._buckets: "OrderedDict[str, deque]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_tracked_keys = max_tracked_keys

    def hit(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Records a hit for `key` unless it would exceed `limit` within
        the trailing `window_seconds`. Returns (allowed, retry_after_seconds)
        — retry_after is 0 when allowed, otherwise how long until the
        oldest hit in the window ages out."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
                return False, retry_after

            bucket.append(now)
            while len(self._buckets) > self._max_tracked_keys:
                self._buckets.popitem(last=False)
            return True, 0

    def reset(self) -> None:
        """Test-only: clears all recorded hits."""
        with self._lock:
            self._buckets.clear()
