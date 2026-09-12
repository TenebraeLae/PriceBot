from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.db.models import Category, Product
from pricebot.domain.catalog import (
    MAX_QUERY_LEN,
    CatalogProduct,
    SearchPage,
    product_card,
)

LIKE_ESCAPE = "\\"


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_catalog_product(row: Product, category_name: str) -> CatalogProduct:
    return CatalogProduct(
        sku=row.sku,
        name=row.name,
        category=category_name,
        description=row.description or "",
        price=row.price,
        stock=row.stock,
        unit=row.unit,
        photo_url=row.photo_url,
        active=row.active,
        sort=row.sort,
    )


async def list_categories_db(session: AsyncSession) -> list[dict[str, object]]:
    result = await session.execute(
        select(Category.id, Category.name, Category.sort)
        .where(Category.active.is_(True))
        .order_by(Category.sort.asc(), Category.name.asc())
    )
    return [{"id": row.id, "name": row.name, "sort": row.sort} for row in result.all()]


async def _category_hints(session: AsyncSession) -> tuple[str, ...]:
    result = await session.execute(
        select(Category.name)
        .where(Category.active.is_(True))
        .order_by(Category.sort.asc(), Category.name.asc())
    )
    return tuple(result.scalars().all())


def _empty_page(
    page: int,
    page_size: int,
    *,
    reason: str | None,
    hint: str | None = None,
    category_hints: tuple[str, ...] = (),
) -> SearchPage:
    return SearchPage(
        items=[],
        page=page,
        page_size=page_size,
        total=0,
        reason=reason,
        hint=hint,
        category_hints=category_hints,
    )


async def search_products_db(
    session: AsyncSession,
    query: str,
    *,
    page: int = 1,
    page_size: int = 10,
    user_status: str = "active",
) -> SearchPage:
    if user_status == "blocked":
        return _empty_page(page, page_size, reason="user_blocked", hint="Поиск недоступен")

    stripped = query.strip()
    if not stripped:
        hints = await _category_hints(session)
        return _empty_page(
            page,
            page_size,
            reason="empty_query",
            hint="Введите запрос",
            category_hints=hints,
        )
    if len(stripped) > MAX_QUERY_LEN:
        return _empty_page(page, page_size, reason="query_too_long")
    if page < 1 or page_size < 1:
        return _empty_page(page, page_size, reason="ok")

    pattern = f"%{escape_like(stripped.casefold())}%"
    filters = (
        Product.active.is_(True),
        Product.search_blob.like(pattern, escape=LIKE_ESCAPE),
    )

    total = int(
        await session.scalar(select(func.count()).select_from(Product).where(*filters)) or 0
    )
    offset = (page - 1) * page_size
    if offset >= total:
        return SearchPage(items=[], page=page, page_size=page_size, total=total, reason="ok")

    rows = await session.execute(
        select(Product, func.coalesce(Category.name, ""))
        .outerjoin(Category, Product.category_id == Category.id)
        .where(*filters)
        .order_by(Product.sort.asc(), Product.sku.asc())
        .offset(offset)
        .limit(page_size)
    )
    items = [to_catalog_product(product, category) for product, category in rows.all()]
    return SearchPage(items=items, page=page, page_size=page_size, total=total, reason="ok")


async def get_product_card(
    session: AsyncSession,
    sku: str,
    *,
    user_status: str = "active",
) -> dict[str, object] | None:
    if user_status == "blocked":
        return None
    row = await session.execute(
        select(Product, func.coalesce(Category.name, ""))
        .outerjoin(Category, Product.category_id == Category.id)
        .where(Product.sku == sku, Product.active.is_(True))
    )
    found = row.first()
    if found is None:
        return None
    product, category_name = found
    return product_card(to_catalog_product(product, category_name))


class LastQueryStore:
    def __init__(self) -> None:
        self._queries: dict[int, str] = {}

    def put(self, user_id: int, query: str) -> None:
        self._queries[user_id] = query

    def get(self, user_id: int) -> str | None:
        return self._queries.get(user_id)
