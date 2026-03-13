"""
Async Riot API HTTP client.

Handles:
- API-key injection via X-Riot-Token header
- Dual-window app rate limiting (500/10s and 30000/10m by default)
- Per-semaphore concurrency cap for in-flight sockets
- 429 → read Retry-After header and sleep
- 5xx → exponential back-off retries
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any

import aiohttp

from config import (
    APP_RATE_LIMIT_LONG,
    APP_RATE_LIMIT_LONG_WINDOW_SEC,
    APP_RATE_LIMIT_SHORT,
    APP_RATE_LIMIT_SHORT_WINDOW_SEC,
    MAX_CONCURRENCY,
    MAX_RETRIES_5XX,
    RIOT_API_KEY,
)

log = logging.getLogger(__name__)


class RiotAPIError(Exception):
    """Raised for non-retryable HTTP errors (4xx except 429)."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


class ServerError(Exception):
    """Raised for 5xx errors so the retry loop can back off and retry."""


class SlidingWindowRateLimiter:
    """
    Async dual-window rate limiter.

    Enforces max calls in fixed windows using request timestamps:
    - short window: e.g. 500 requests / 10 seconds
    - long window:  e.g. 30000 requests / 600 seconds
    """

    def __init__(self, windows: list[tuple[int, float]]) -> None:
        self._windows: list[tuple[int, float, deque[float]]] = [
            (limit, seconds, deque()) for limit, seconds in windows
        ]
        self._lock = asyncio.Lock()
        self._cooldown_until = 0.0
        # Smooth bursts by spacing request starts by at least the most strict
        # average interval implied by the configured windows.
        self._min_interval = max(seconds / limit for limit, seconds in windows)
        self._next_slot_at = 0.0

    async def acquire(self) -> None:
        """Block until one request can be scheduled across all windows."""
        while True:
            async with self._lock:
                now = time.monotonic()
                wait_for = max(0.0, self._cooldown_until - now)

                if self._next_slot_at > now:
                    wait_for = max(wait_for, self._next_slot_at - now)

                for limit, seconds, timestamps in self._windows:
                    cutoff = now - seconds
                    while timestamps and timestamps[0] <= cutoff:
                        timestamps.popleft()

                    if len(timestamps) >= limit:
                        oldest = timestamps[0]
                        wait_for = max(wait_for, (oldest + seconds) - now)

                if wait_for <= 0.0:
                    stamp = time.monotonic()
                    for _, _, timestamps in self._windows:
                        timestamps.append(stamp)
                    self._next_slot_at = max(self._next_slot_at, stamp) + self._min_interval
                    return

            await asyncio.sleep(wait_for + 0.002)

    async def cooldown(self, seconds: float) -> None:
        """Apply a temporary global cooldown (used after 429 Retry-After)."""
        if seconds <= 0:
            return

        async with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)


class RiotClient:
    """
    Context-manager async client.

    Usage::

        async with RiotClient() as client:
            data = await client.get("https://<platform>.api.riotgames.com/...")
    """

    def __init__(self, max_concurrency: int = MAX_CONCURRENCY) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)
        self._rate_limiter = SlidingWindowRateLimiter(
            windows=[
                (APP_RATE_LIMIT_SHORT, APP_RATE_LIMIT_SHORT_WINDOW_SEC),
                (APP_RATE_LIMIT_LONG, APP_RATE_LIMIT_LONG_WINDOW_SEC),
            ]
        )
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "RiotClient":
        self._session = aiohttp.ClientSession(
            headers={"X-Riot-Token": RIOT_API_KEY},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def get(self, url: str, **params: Any) -> Any:
        """
        Perform a GET request and return the parsed JSON body.

        Automatically retries on 429 (rate-limited) and 5xx errors.
        Raises RiotAPIError for other 4xx responses.
        """
        return await self._get_with_retry(url, **params)

    async def _get_with_retry(self, url: str, **params: Any) -> Any:
        """Inner GET with 429-aware retry loop and 5xx tenacity decorator."""
        # tenacity doesn't sit well on coroutines with dynamic `self`, so we
        # inline the 5xx retry logic manually for clarity and correctness.
        attempt = 0
        delay = 1.0
        while True:
            try:
                return await self._get_once(url, **params)
            except ServerError:
                attempt += 1
                if attempt >= MAX_RETRIES_5XX:
                    raise
                wait = min(delay * (2 ** (attempt - 1)), 60.0)
                log.warning("5xx on %s — retry %d/%d in %.1fs", url, attempt, MAX_RETRIES_5XX, wait)
                await asyncio.sleep(wait)
            except _RateLimitedError as exc:
                log.warning("429 on %s — sleeping %ds (Retry-After)", url, exc.retry_after)
                await self._rate_limiter.cooldown(exc.retry_after + 0.25)
                await asyncio.sleep(exc.retry_after + 0.5)
                # loop and retry

    async def _get_once(self, url: str, **params: Any) -> Any:
        assert self._session is not None, "RiotClient must be used as an async context manager"

        await self._rate_limiter.acquire()

        async with self._sem:
            async with self._session.get(url, params=params or None) as resp:
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "1"))
                    raise _RateLimitedError(retry_after)

                if resp.status >= 500:
                    raise ServerError(f"HTTP {resp.status} for {url}")

                if resp.status >= 400:
                    raise RiotAPIError(resp.status, url)

                return await resp.json()


class _RateLimitedError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Rate limited; retry after {retry_after}s")
        self.retry_after = retry_after
