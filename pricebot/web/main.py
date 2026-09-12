import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from pricebot.config import Settings, get_settings
from pricebot.db.session import create_schema, make_engine, make_session_factory
from pricebot.services.notify import TelegramNotifier, set_notifier
from pricebot.web.admin import router as admin_router
from pricebot.web.cart import router as cart_router
from pricebot.web.catalog import router as catalog_router
from pricebot.web.deps import get_settings_dep, reset_session_factory, set_session_factory
from pricebot.web.metrics import mount_metrics
from pricebot.web.orders import router as orders_router
from pricebot.web.payments import router as payments_router
from pricebot.web.telegram import router as telegram_router
from pricebot.web.tickets import router as tickets_router

APP_DIR = Path(__file__).resolve().parent / "app"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        settings = get_settings()
    except ValidationError:
        yield
        return
    Path(settings.imports_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    try:
        await create_schema(engine)
        factory = make_session_factory(engine)
        set_session_factory(factory)
        set_notifier(TelegramNotifier(settings.bot_token))
        app.state.engine = engine
        app.state.bot = None
        app.state.dispatcher = None
        if settings.bot_mode == "webhook":
            from pricebot.bot.main import build_dispatcher
            from pricebot.bot.session import make_bot

            bot = make_bot(settings.bot_token)
            app.state.bot = bot
            app.state.dispatcher = build_dispatcher(settings, factory)
        yield
    finally:
        bot = getattr(app.state, "bot", None)
        if bot is not None:
            await bot.session.close()
        reset_session_factory()
        await engine.dispose()


app = FastAPI(title="PriceBot", lifespan=lifespan)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("pricebot")
mount_metrics(app)


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка"})

app.include_router(admin_router)
app.include_router(catalog_router)
app.include_router(cart_router)
app.include_router(orders_router)
app.include_router(payments_router)
app.include_router(tickets_router)
app.include_router(telegram_router)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


def _slot_payload() -> dict[str, object]:
    return {"slot": "miniapp", "stage": "E", "ready": True}


@app.get("/api/v1/slot")
async def miniapp_slot() -> dict[str, object]:
    return _slot_payload()


@app.get("/api/slot")
async def miniapp_slot_alias() -> dict[str, object]:
    return _slot_payload()


@app.get("/media/{rest:path}")
async def media_file(
    rest: str,
    settings: Settings = Depends(get_settings_dep),
) -> FileResponse:
    root = Path(settings.media_dir).resolve()
    target = (root / rest).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(target)


app.mount("/app", StaticFiles(directory=APP_DIR, html=True), name="miniapp")
