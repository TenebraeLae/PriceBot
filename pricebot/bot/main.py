import asyncio
import logging
from pathlib import Path

from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pricebot.bot.handlers import AdminReplyPendingStore, SupportPendingStore, build_router
from pricebot.bot.session import make_bot
from pricebot.bot.texts import default_info_path
from pricebot.config import Settings, get_settings
from pricebot.db.session import create_schema, make_engine, make_session_factory
from pricebot.services.search import LastQueryStore


def build_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    query_store: LastQueryStore | None = None,
    info_path: Path | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher["settings"] = settings
    dispatcher["session_factory"] = session_factory
    dispatcher["query_store"] = query_store or LastQueryStore()
    dispatcher["support_store"] = SupportPendingStore()
    dispatcher["admin_reply_store"] = AdminReplyPendingStore()
    dispatcher["info_path"] = info_path or default_info_path()
    dispatcher.include_router(build_router())
    return dispatcher


async def run_bot(settings: Settings) -> None:
    Path(settings.imports_dir).mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    await create_schema(engine)
    factory = make_session_factory(engine)
    bot = make_bot(settings.bot_token)
    dispatcher = build_dispatcher(settings, factory)
    if settings.bot_mode == "webhook":
        await bot.set_webhook(
            f"{settings.public_base_url.rstrip('/')}/telegram/webhook",
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await bot.session.close()
            await engine.dispose()
        return
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
