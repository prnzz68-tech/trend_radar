import asyncio
import time

import pytest

from src.utils.throttle import DomainThrottler


@pytest.mark.asyncio
async def test_same_domain_is_rate_limited() -> None:
    # 5 req/sec => min_interval 0.2s. 4 запроса => >= 0.6s (3 интервала).
    throttler = DomainThrottler(rate_per_sec=5.0)
    url = "https://example.com/path"

    start = time.monotonic()
    for _ in range(4):
        await throttler.acquire(url)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.6, f"expected >= 0.6s, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_different_domains_not_blocked() -> None:
    throttler = DomainThrottler(rate_per_sec=1.0)

    start = time.monotonic()
    await throttler.acquire("https://a.com/x")
    await throttler.acquire("https://b.com/x")
    await throttler.acquire("https://c.com/x")
    elapsed = time.monotonic() - start

    # Разные домены не ждут друг друга.
    assert elapsed < 0.3, f"expected fast, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_concurrent_same_domain_serialized() -> None:
    # 10 req/sec => 0.1s интервал. 3 параллельные корутины к одному домену => >= 0.2s.
    throttler = DomainThrottler(rate_per_sec=10.0)
    url = "https://example.com/x"

    async def call() -> None:
        await throttler.acquire(url)

    start = time.monotonic()
    await asyncio.gather(call(), call(), call())
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2, f"expected >= 0.2s, got {elapsed:.3f}s"