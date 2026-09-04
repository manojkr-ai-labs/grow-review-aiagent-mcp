"""Client-side pacing for the Groq free tier.

Groq caps a free key on four axes at once, and on this workload the tokens
ceiling binds long before the requests one: a labeling call carries the system
rules plus ten stratified samples, so ~1.4K tokens a call means 8K tokens per
minute allows only about five calls, not the thirty requests per minute the
same tier permits. The limiter therefore paces on whichever axis is tighter,
and refuses to keep going once a single run has spent the daily allowance.
"""

from __future__ import annotations

import asyncio
import threading
import time

from langchain_core.rate_limiters import BaseRateLimiter


class DailyBudgetExhausted(RuntimeError):
    """Raised when a run has used the calls its daily token allowance affords."""


class FreeTierRateLimiter(BaseRateLimiter):
    """Token bucket over the tighter of the request and token per-minute limit.

    The bucket starts full. A fresh process has spent nothing on the account
    yet, so the first calls of a run are free to go straight out; only once a
    minute's worth is gone does pacing kick in.
    """

    def __init__(
        self,
        *,
        requests_per_minute: int,
        requests_per_day: int,
        tokens_per_minute: int,
        tokens_per_day: int,
        tokens_per_request: int,
        check_every_n_seconds: float = 0.25,
    ) -> None:
        tokens_per_request = max(tokens_per_request, 1)
        self.calls_per_minute = min(
            float(requests_per_minute), tokens_per_minute / tokens_per_request
        )
        self.calls_per_day = min(requests_per_day, tokens_per_day // tokens_per_request)
        self._refill_per_second = self.calls_per_minute / 60.0
        self._check_every_n_seconds = check_every_n_seconds
        self._lock = threading.Lock()
        self._available = self.calls_per_minute
        self._updated_at = time.monotonic()
        self.calls_made = 0

    def _try_consume(self) -> bool:
        with self._lock:
            if self.calls_made >= self.calls_per_day:
                raise DailyBudgetExhausted(
                    f"used the free tier's {self.calls_per_day} calls for today"
                )
            now = time.monotonic()
            self._available = min(
                self.calls_per_minute,
                self._available + (now - self._updated_at) * self._refill_per_second,
            )
            self._updated_at = now
            if self._available < 1.0:
                return False
            self._available -= 1.0
            self.calls_made += 1
            return True

    def acquire(self, *, blocking: bool = True) -> bool:
        if not blocking:
            return self._try_consume()
        while not self._try_consume():
            time.sleep(self._check_every_n_seconds)
        return True

    async def aacquire(self, *, blocking: bool = True) -> bool:
        if not blocking:
            return self._try_consume()
        while not self._try_consume():
            await asyncio.sleep(self._check_every_n_seconds)
        return True
