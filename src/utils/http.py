# src/utils/http.py

from typing import Any

import httpx
import structlog

from src.settings import settings
from src.utils.retry import async_retry
from src.utils.throttle import DomainThrottler

log = structlog.get_logger(__name__)

USER_AGENT = "trend-radar/0.1 (+https://github.com/trend-radar)"
DEFAULT_TIMEOUT = httpx.Timeout(15.0)

# Единый на процесс throttler и клиент.
_throttler = DomainThrottler(settings.HTTP_REQUESTS_PER_DOMAIN_PER_SEC)
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Ленивый общий AsyncClient (общий UA, таймауты, follow_redirects)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


@async_retry(attempts=3, base_delay=1.0, exceptions=(httpx.HTTPError,))
async def fetch_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    """GET с per-domain throttling и ретраями. Возвращает тело ответа."""
    await _throttler.acquire(url)
    client = get_client()
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return resp.content


@async_retry(attempts=3, base_delay=1.0, exceptions=(httpx.HTTPError,))
async def fetch_json(url: str, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
    """GET JSON с throttling и ретраями (для будущих API-источников)."""
    await _throttler.acquire(url)
    client = get_client()
    resp = await client.get(url, headers=headers, **kwargs)
    resp.raise_for_status()
    return resp.json()


@async_retry(attempts=3, base_delay=1.0, exceptions=(httpx.HTTPError,))
async def post_json(
    url: str,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """POST JSON с throttling и ретраями для API-источников."""
    await _throttler.acquire(url)
    client = get_client()
    resp = await client.post(url, headers=headers, **kwargs)
    resp.raise_for_status()
    return resp.json()
