from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger("pricebot.telegram")

T = TypeVar("T")


async def call_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    sleeper: Callable[[float], Awaitable[None]],
) -> T:
    try:
        return await operation()
    except Exception as exc:
        delay = getattr(exc, "retry_after", None)
        if delay is None:
            raise
        seconds = float(delay)
        logger.warning("telegram retry_after=%.3f", seconds)
        await sleeper(seconds)
        return await operation()
