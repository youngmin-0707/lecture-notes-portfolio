"""운영 SQLite DB 백업 (2026-10-18).

DB 파일(`data/lecture_notes.db`)이 강의 데이터의 유일한 사본이라, 디스크 고장·실수로 인한
삭제에 대비해 날짜별 사본을 남긴다. 백엔드가 쓰는 도중에도 일관된 사본을 얻기 위해 파일을
그대로 복사하지 않고 sqlite3 온라인 백업 API(`Connection.backup`)를 쓴다.

- 정기 백업: `scripts/backup_db.py`를 launchd가 매일 실행한다.
- 마이그레이션 전 백업: `alembic/env.py`가 업그레이드/다운그레이드 직전에 호출한다.

사본은 로컬(`data/backups/`, gitignore 대상)과 iCloud Drive(노트북 고장 대비) 두 곳에 두고,
`RETENTION_DAYS`보다 오래된 사본은 지운다. PostgreSQL(테스트 하니스)은 대상이 아니다.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.fs import ensure_private_dir, ensure_private_file

logger = logging.getLogger("app.core.backup")

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOCAL_BACKUP_DIR = BACKEND_DIR / "data" / "backups"
ICLOUD_BACKUP_DIR = (
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "lecture-notes-backups"
)
RETENTION_DAYS = 14
_PREFIX = "lecture_notes-"


def sqlite_path_from_url(database_url: str) -> Path | None:
    """SQLite 파일 URL이면 절대 경로를, 아니면(PostgreSQL·메모리 DB) `None`을 돌려준다."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


def backup_sqlite(
    db_path: Path,
    *,
    reason: str,
    local_dir: Path = LOCAL_BACKUP_DIR,
    mirror_dir: Path | None = ICLOUD_BACKUP_DIR,
    retention_days: int = RETENTION_DAYS,
) -> Path:
    """`db_path`의 일관된 사본을 만들고 무결성을 확인한 뒤 경로를 돌려준다.

    Args:
        reason: 파일명에 붙는 사유 (`daily`, `pre-migration` 등).
        mirror_dir: 사본을 한 벌 더 둘 곳. `None`이면 생략. 복사 실패는 경고만 남긴다 —
            iCloud가 꺼져 있어도 로컬 백업까지 실패로 만들지 않기 위함.

    Raises:
        FileNotFoundError: 원본 DB가 없을 때.
        RuntimeError: 사본의 `integrity_check`가 `ok`가 아닐 때 (깨진 사본은 지운다).
    """
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    ensure_private_dir(local_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = local_dir / f"{_PREFIX}{stamp}-{reason}.db"

    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if result != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError(f"backup integrity_check failed: {result}")
    ensure_private_file(target)

    _prune(local_dir, retention_days)
    if mirror_dir is not None:
        try:
            ensure_private_dir(mirror_dir)
            shutil.copy2(target, mirror_dir / target.name)
            _prune(mirror_dir, retention_days)
        except OSError:
            logger.warning("backup mirror copy failed: dir=%s", mirror_dir, exc_info=True)

    logger.info("sqlite backup created: %s", target)
    return target


def _prune(directory: Path, retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    for old in directory.glob(f"{_PREFIX}*.db"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
