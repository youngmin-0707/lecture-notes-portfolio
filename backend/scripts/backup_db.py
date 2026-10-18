"""운영 SQLite DB 정기 백업 진입점 (launchd `com.lecturenotes.backup`이 매일 실행).

사용법 (backend/ 에서): .venv/bin/python scripts/backup_db.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.backup import backup_sqlite, sqlite_path_from_url  # noqa: E402
from app.core.config import settings  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db_path = sqlite_path_from_url(settings.DATABASE_URL)
    if db_path is None:
        logging.error("DATABASE_URL is not a SQLite file; nothing to back up")
        return 1
    backup_sqlite(db_path, reason="daily")
    return 0


if __name__ == "__main__":
    sys.exit(main())
