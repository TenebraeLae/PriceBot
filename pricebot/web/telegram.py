import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from pricebot.config import Settings
from pricebot.web.deps import get_settings_dep

logger = logging.getLogger("pricebot.telegram")

router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> JSONResponse:
    if (x_telegram_bot_api_secret_token or "") != settings.telegram_webhook_secret:
        logger.warning("telegram webhook rejected: bad secret")
        raise HTTPException(status_code=403, detail="Недействительный секрет Telegram")
    payload = await request.json()
    dispatcher = getattr(request.app.state, "dispatcher", None)
    bot = getattr(request.app.state, "bot", None)
    if dispatcher is not None and bot is not None:
        from aiogram.types import Update

        update = Update.model_validate(payload, context={"bot": bot})
        message = payload.get("message") if isinstance(payload, dict) else None
        has_document = isinstance(message, dict) and message.get("document")
        if has_document:

            async def _feed() -> None:
                try:
                    await dispatcher.feed_update(bot, update)
                except Exception:
                    logger.exception("telegram document update failed")

            asyncio.create_task(_feed())
            return JSONResponse({"ok": True})
        await dispatcher.feed_update(bot, update)
    return JSONResponse({"ok": True})
