import asyncio
import time
from urllib.parse import urlparse

import structlog

log = structlog.get_logger(__name__)


class DomainThrottler:
    """Ограничивает частоту запросов к каждому домену: не чаще rate запросов/сек.

    Реализация: на домен — asyncio.Lock + отметка времени последнего запроса.
    Перед запросом ждём, пока не пройдёт min_interval = 1/rate с прошлого.
    """

    def __init__(self, rate_per_sec: float = 1.0) -> None:
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._guard = asyncio.Lock()

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc or url

    async def _get_lock(self, domain: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(domain)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[domain] = lock
            return lock

    async def acquire(self, url: str) -> None:
        if self._min_interval <= 0:
            return
        domain = self._domain(url)
        lock = await self._get_lock(domain)
        async with lock:
            now = time.monotonic()
            last = self._last.get(domain, 0.0)
            wait = self._min_interval - (now - last)
            if wait > 0:
                log.debug("throttle.wait", domain=domain, seconds=round(wait, 3))
                await asyncio.sleep(wait)
            self._last[domain] = time.monotonic()