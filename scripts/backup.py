from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pricebot.config import get_settings
from pricebot.services.backup import rotate_backups, run_pg_dump, write_backup_file

MOSCOW = ZoneInfo("Europe/Moscow")


def main() -> None:
    settings = get_settings()
    now = datetime.now(MOSCOW)
    try:
        run_pg_dump(
            backups_dir=settings.backups_dir,
            database_url=settings.database_url,
            now=now,
        )
    except OSError:
        write_backup_file(settings.backups_dir, b"-- pg_dump unavailable\n", now=now)
    removed = rotate_backups(
        settings.backups_dir,
        retention_days=settings.backup_retention_days,
        now=now,
    )
    print(f"rotated {len(removed)} file(s)")


if __name__ == "__main__":
    main()
