# src/utils/retry.py

import asyncio
import functools
from typing import Awaitable, Callable, TypeVar

import structlog

T = TypeVar("T")
log = structlog.get_logger(__name__)


def async_retry(
    attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
):
    """Экспоненциальная пауза: base_delay * 2^(attempt-1). 3 попытки -> 1s, 2s, 4s."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == attempts:
                        break
                    delay = base_delay * (2 ** (attempt - 1))
                    log.warning(
                        "retry",
                        func=func.__name__,
                        attempt=attempt,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator