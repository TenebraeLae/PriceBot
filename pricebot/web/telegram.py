import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from pricebot.config import Settings
from pricebot.web.auth import constant_time_equal
from pricebot.web.deps import get_settings_dep
from pricebot.web.update_dedup import SEEN_UPDATES

logger = logging.getLogger("pricebot.telegram")

router = APIRouter()


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        logger.exception("background task failed", exc_info=exc)


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> JSONResponse:
    if not constant_time_equal(
        x_telegram_bot_api_secret_token or "", settings.telegram_webhook_secret
    ):
        logger.warning("telegram webhook rejected: bad secret")
        raise HTTPException(status_code=403, detail="Недействительный секрет Telegram")
    payload = await request.json()
    dispatcher = getattr(request.app.state, "dispatcher", None)
    bot = getattr(request.app.state, "bot", None)
    if dispatcher is not None and bot is not None:
        from aiogram.types import Update

        update = Update.model_validate(payload, context={"bot": bot})
        update_key = str(update.update_id)
        if not SEEN_UPDATES.add_new(update_key):
            return JSONResponse({"ok": True})

        async def _feed() -> None:
            try:
                await dispatcher.feed_update(bot, update)
            except Exception:
                SEEN_UPDATES.discard(update_key)
                logger.exception("telegram update failed")

        task = asyncio.create_task(_feed())
        task.add_done_callback(_log_task_error)
    return JSONResponse({"ok": True})
