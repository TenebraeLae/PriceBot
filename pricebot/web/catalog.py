from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.db.models import User
from pricebot.domain.catalog import CatalogProduct, SearchPage
from pricebot.domain.photo import resolve_product_photo
from pricebot.services.search import get_product_card, list_categories_db, search_products_db
from pricebot.web.deps import get_session, get_settings_dep, require_webapp_user

router = APIRouter(prefix="/api/v1")


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value


def _product_payload(item: CatalogProduct) -> dict[str, object]:
    return {
        "sku": item.sku,
        "name": item.name,
        "category": item.category,
        "description": item.description,
        "price": str(item.price),
        "stock": str(item.stock),
        "unit": item.unit,
        "photo_url": resolve_product_photo(item.photo_url),
        "availability": "в наличии" if item.stock > 0 else "нет",
    }


def _page_payload(page: SearchPage) -> dict[str, object]:
    return {
        "items": [_product_payload(item) for item in page.items],
        "page": page.page,
        "page_size": page.page_size,
        "total": page.total,
        "reason": page.reason,
        "hint": page.hint,
        "category_hints": list(page.category_hints),
    }


@router.get("/categories")
async def list_categories(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    if user.status == "blocked":
        return {"items": [], "reason": "user_blocked"}
    return {"items": await list_categories_db(session), "reason": "ok"}


@router.get("/search")
async def search_catalog(
    q: str = Query(default=""),
    page: int = Query(default=1),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    result = await search_products_db(
        session,
        q,
        page=page,
        page_size=settings.page_size_web,
        user_status=user.status,
    )
    return _page_payload(result)


@router.get("/products/{sku}")
async def product_by_sku(
    sku: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    if user.status == "blocked":
        raise HTTPException(status_code=403, detail="Поиск недоступен")
    card = await get_product_card(session, sku, user_status=user.status)
    if card is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return {key: _json_value(value) for key, value in card.items()}
