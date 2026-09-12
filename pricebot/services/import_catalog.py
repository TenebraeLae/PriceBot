from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.db.models import CartItem, Category, PriceImport, Product
from pricebot.domain.access import ensure_admin
from pricebot.domain.catalog import CatalogProduct, catalog_search_blob
from pricebot.domain.excel import ParseResult, RowError, parse_excel
from pricebot.services.cache import invalidate_search_cache

ERROR_REPORT_LIMIT = 20


@dataclass(frozen=True)
class ImportReport:
    status: str
    rows_ok: int
    rows_err: int
    reject_reason: str | None
    import_id: int | None
    saved_path: str
    errors: tuple[RowError, ...] = ()


def save_import_file(imports_dir: Path | str, filename: str, content: bytes) -> Path:
    directory = Path(imports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe = Path(filename).name or "price.xlsx"
    destination = directory / f"{stamp}_{safe}"
    destination.write_bytes(content)
    return destination


def _now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


async def _get_or_create_category(session: AsyncSession, name: str) -> Category | None:
    if not name:
        return None
    found = await session.execute(select(Category).where(Category.name == name))
    category = found.scalar_one_or_none()
    if category is not None:
        return category
    category = Category(name=name, sort=0, active=True)
    session.add(category)
    await session.flush()
    return category


async def _rebuild_active_catalog(
    session: AsyncSession,
    rows: list[CatalogProduct],
    import_id: int,
) -> None:
    await session.execute(delete(CartItem))
    await session.execute(delete(Product))
    for row in rows:
        category = await _get_or_create_category(session, row.category)
        session.add(
            Product(
                sku=row.sku,
                name=row.name,
                category_id=category.id if category else None,
                description=row.description or None,
                price=row.price,
                stock=row.stock,
                unit=row.unit,
                photo_url=row.photo_url,
                active=row.active,
                sort=row.sort,
                import_id=import_id,
                search_blob=catalog_search_blob(row.name, row.sku, row.category),
            )
        )


def _report_from_parse(
    parsed: ParseResult,
    *,
    import_id: int | None,
    saved_path: str,
) -> ImportReport:
    return ImportReport(
        status=parsed.import_status,
        rows_ok=len(parsed.rows_ok),
        rows_err=len(parsed.rows_err),
        reject_reason=parsed.reject_reason,
        import_id=import_id,
        saved_path=saved_path,
        errors=tuple(parsed.rows_err[:ERROR_REPORT_LIMIT]),
    )


async def apply_price_import(
    session: AsyncSession,
    *,
    content: bytes,
    filename: str,
    admin_id: int,
    admin_ids: list[int] | tuple[int, ...],
    imports_dir: Path | str,
    max_rows: int = 50_000,
    timezone_name: str = "Europe/Moscow",
    redis_url: str | None = None,
) -> ImportReport:
    ensure_admin(admin_id, admin_ids)
    saved = save_import_file(imports_dir, filename, content)
    parsed = parse_excel(content, max_rows=max_rows)
    finished = _now(timezone_name)

    batch = PriceImport(
        filename=saved.name,
        admin_id=admin_id,
        rows_ok=len(parsed.rows_ok),
        rows_err=len(parsed.rows_err),
        status="pending",
    )
    session.add(batch)
    await session.flush()

    if not parsed.accepted or not parsed.rows_ok:
        batch.status = "rejected"
        batch.finished_at = finished
        await session.commit()
        return _report_from_parse(parsed, import_id=batch.id, saved_path=str(saved))

    try:
        await _rebuild_active_catalog(session, parsed.rows_ok, batch.id)
        batch.status = "applied"
        batch.finished_at = finished
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    await invalidate_search_cache(redis_url)
    return _report_from_parse(parsed, import_id=batch.id, saved_path=str(saved))
