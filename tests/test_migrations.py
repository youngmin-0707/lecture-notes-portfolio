"""Alembic 마이그레이션이 SQLite/PostgreSQL 양쪽에서 성공하는지 검증한다 (T-04 DoD).

`docker-compose.test.yml` 컨테이너가 떠 있어야 하는 PostgreSQL 케이스는
`integration` 마커를 붙여 구분한다 (§7 T-04).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "sessions",
    "transcripts",
    "transcript_segments",
    "summaries",
    "glossary_terms",
}


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _table_names(database_url: str) -> set[str]:
    engine = sa.create_engine(database_url, future=True)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_upgrade_and_downgrade_on_sqlite(tmp_path) -> None:
    db_path = tmp_path / "alembic_test.db"
    database_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(database_url)

    command.upgrade(cfg, "head")
    tables = _table_names(database_url)
    assert EXPECTED_TABLES.issubset(tables)

    command.downgrade(cfg, "base")
    tables_after_downgrade = _table_names(database_url)
    assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)


def test_migration_seeds_100_default_glossary_terms_on_sqlite(tmp_path) -> None:
    """T-22 DoD: 초기 마이그레이션 시 기본 용어집이 채워진다."""
    from app.glossary.default_terms import DEFAULT_GLOSSARY_TERMS

    db_path = tmp_path / "alembic_seed_test.db"
    database_url = f"sqlite:///{db_path}"
    cfg = _alembic_config(database_url)

    command.upgrade(cfg, "head")
    engine = sa.create_engine(database_url, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text("SELECT term FROM glossary_terms")).fetchall()
    finally:
        engine.dispose()
    seeded_terms = {row[0] for row in rows}
    assert len(seeded_terms) == len(DEFAULT_GLOSSARY_TERMS) == 100
    assert "PostgreSQL" in seeded_terms

    command.downgrade(cfg, "base")
    tables_after_downgrade = _table_names(database_url)
    assert "glossary_terms" not in tables_after_downgrade


def _ensure_database_exists(base_url: sa.URL, dbname: str) -> None:
    """`dbname` 데이터베이스가 없으면 만든다. `postgres` 관리용 DB에 접속해 실행한다."""
    admin_url = base_url.set(database="postgres")
    admin_engine = sa.create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": dbname}
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    finally:
        admin_engine.dispose()


@pytest.mark.integration
def test_migration_upgrade_and_downgrade_on_postgres() -> None:
    """실제 `alembic upgrade`/`downgrade` 왕복을 검증한다.

    `tests/conftest.py`의 세션 스코프 `engine` 픽스처는 같은 서버의 `TEST_DATABASE_URL`
    DB에 `Base.metadata.create_all`로 직접 테이블을 만들어 다른 테스트 전반에서 재사용한다.
    이 테스트가 그 DB를 공유하면 (수집 순서상 이 테스트 앞에서 `engine` 픽스처가 먼저
    쓰였을 때) alembic이 모르는 테이블이 이미 있어 `CREATE TABLE`이 "already exists"로
    깨지거나, 반대로 이 테스트의 `downgrade(base)`가 다른 테스트가 의존 중인 테이블을
    지워버린다. 그래서 이름을 달리한 **전용 DB**를 이 테스트 실행 시 직접 만들어 완전히
    격리한다 — 다른 픽스처의 생명주기와 절대 겹치지 않는다.
    """
    base_database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5433/signup_test",
    )
    base_url = sa.make_url(base_database_url)
    migration_dbname = f"{base_url.database}_migrations_test"
    _ensure_database_exists(base_url, migration_dbname)
    # `str(URL)`는 비밀번호를 "***"로 가린다 (SQLAlchemy 기본 동작) — 실제 접속 문자열에는
    # 그대로 두면 안 되므로 `render_as_string(hide_password=False)`로 원문 비밀번호를 유지한다.
    database_url = base_url.set(database=migration_dbname).render_as_string(hide_password=False)

    cfg = _alembic_config(database_url)

    try:
        command.downgrade(cfg, "base")
    except Exception:
        pass  # 이전 실행 잔여물 정리 목적. 실패해도 upgrade 단계에서 실제로 검증된다.

    command.upgrade(cfg, "head")
    tables = _table_names(database_url)
    assert EXPECTED_TABLES.issubset(tables)

    command.downgrade(cfg, "base")
    tables_after_downgrade = _table_names(database_url)
    assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)
