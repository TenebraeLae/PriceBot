from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pricebot.db.models import Base
from pricebot.platform_env import normalize_database_url

_PRODUCT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_products_active_sort ON products (active, sort)",
    "CREATE INDEX IF NOT EXISTS ix_products_category_id ON products (category_id)",
)


def make_engine(database_url: str) -> AsyncEngine:
    url = normalize_database_url(database_url)
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if "+asyncpg" in url:
        kwargs["pool_size"] = 3
        kwargs["max_overflow"] = 2
        kwargs["pool_recycle"] = 1800
    return create_async_engine(url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        for statement in _PRODUCT_INDEXES:
            await connection.execute(text(statement))
