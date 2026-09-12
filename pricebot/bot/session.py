from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramRetryAfter
from aiolimiter import AsyncLimiter

from pricebot.domain.telegram import call_with_retry

logger = logging.getLogger("pricebot.telegram")


class RateLimitRetryMiddleware(BaseRequestMiddleware):
    def __init__(self, limiter: AsyncLimiter) -> None:
        super().__init__()
        self.limiter = limiter

    async def __call__(self, make_request, bot, method):
        async with self.limiter:

            async def _once():
                return await make_request(bot, method)

            try:
                return await call_with_retry(_once, sleeper=asyncio.sleep)
            except TelegramRetryAfter as exc:
                logger.warning("telegram retry_after=%s", exc.retry_after)
                await asyncio.sleep(float(exc.retry_after))
                return await make_request(bot, method)


def make_bot(token: str, *, rate: float = 28) -> Bot:
    bot = Bot(token=token)
    bot.session.middleware(RateLimitRetryMiddleware(AsyncLimiter(rate, 1)))
    return bot
