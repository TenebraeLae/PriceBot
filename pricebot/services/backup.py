from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("pricebot.backup")

MOSCOW = ZoneInfo("Europe/Moscow")


def rotate_backups(
    directory: Path | str,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[Path]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    current = now or datetime.now(MOSCOW)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MOSCOW)
    cutoff = current - timedelta(days=retention_days)
    removed: list[Path] = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=current.tzinfo)
        if mtime < cutoff:
            path.unlink()
            removed.append(path)
            logger.info("backup rotated: %s", path.name)
    return removed


def write_backup_file(directory: Path | str, content: bytes, *, now: datetime | None = None) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(MOSCOW)).strftime("%Y%m%dT%H%M%S")
    destination = root / f"pricebot-{stamp}.sql"
    destination.write_bytes(content)
    logger.info("backup written: %s", destination.name)
    return destination


def run_pg_dump(
    *,
    backups_dir: Path | str,
    database_url: str,
    now: datetime | None = None,
    runner: Callable[..., object] | None = None,
) -> Path:
    root = Path(backups_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(MOSCOW)).strftime("%Y%m%dT%H%M%S")
    destination = root / f"pricebot-{stamp}.sql"
    dump_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    command = ["pg_dump", dump_url]
    execute = runner or subprocess.run
    with destination.open("wb") as handle:
        execute(command, check=True, stdout=handle)
    logger.info("backup written: %s", destination.name)
    return destination
