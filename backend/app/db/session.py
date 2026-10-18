"""DB 엔진/세션 및 FastAPI 의존성 `get_db`.

dialect 중립 (§0 D9, §2.3): 실사용은 SQLite, 테스트 하니스는 기존 PostgreSQL을 그대로 쓴다.
- SQLite: 멀티스레드 접근을 허용해야 하는 FastAPI 요청 흐름을 위해 `check_same_thread=False`가
  필요하고, FK CASCADE가 기본적으로 비활성화되어 있어 연결마다 `PRAGMA foreign_keys=ON`을 켠다.
  또한 파일 경로의 부모 디렉토리가 없으면 sqlite3가 그냥 실패하므로 미리 생성한다.
- PostgreSQL: 기존과 동일하게 동작한다 (변경 없음).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.fs import ensure_private_dir, ensure_private_file


def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def _sqlite_db_path(url: str) -> Path | None:
    database = make_url(url).database
    if not database or database == ":memory:":
        return None
    return Path(database).resolve()


def _build_engine(database_url: str) -> Engine:
    if _is_sqlite(database_url):
        db_path = _sqlite_db_path(database_url)
        if db_path is not None:
            ensure_private_dir(db_path.parent)
        engine = create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            # sqlite는 최초 연결 시점에 DB 파일을 만든다 — 그때 이미 파일이 있으므로
            # 여기서 매 연결마다 0600을 강제한다 (§3.7, T-38에서 0644로 새고 있던 걸 발견).
            if db_path is not None:
                ensure_private_file(db_path)

        return engine

    return create_engine(database_url, future=True, pool_pre_ping=True)


engine = _build_engine(settings.DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """요청 단위 DB 세션을 제공한다. 정상 종료 시 커밋, 예외 발생 시 롤백한다."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
