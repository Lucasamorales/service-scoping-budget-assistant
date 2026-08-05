"""In-memory rate limiting.

Best-effort protection against a runaway client or a shared link being
hammered. Per-process and lost on restart, which is fine on Cloud Run: each
instance enforces its own ceiling, and the upgrade path for coordinated abuse
is an external store, not a more elaborate local one.

Keyed by client IP by default. When a session is present the subject is used
instead, so one person behind a NAT is not punished for their colleagues.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

__all__ = ["RateLimitExceededError", "RateLimiter"]


class RateLimitExceededError(Exception):
    """The caller has used their budget for this window."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Rate limit exceeded")
        self.retry_after = max(retry_after, 1)


@dataclass
class RateLimiter:
    """Sliding window of timestamps per key."""

    limit: int
    window_seconds: int
    _hits: dict[str, deque[float]]
    _lock: threading.Lock

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = max(limit, 1)
        self.window_seconds = max(window_seconds, 1)
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> None:
        """Record one hit, or raise if the key is over budget."""
        moment = time.monotonic() if now is None else now
        floor = moment - self.window_seconds

        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= floor:
                bucket.popleft()

            if len(bucket) >= self.limit:
                retry_after = int(bucket[0] + self.window_seconds - moment) + 1
                raise RateLimitExceededError(retry_after)

            bucket.append(moment)

            # Bound memory: drop keys that have gone quiet. Checked opportunistically
            # so a busy process does not walk the whole map on every request.
            if len(self._hits) > 10_000:
                stale = [k for k, v in self._hits.items() if not v or v[-1] <= floor]
                for key_name in stale:
                    del self._hits[key_name]
