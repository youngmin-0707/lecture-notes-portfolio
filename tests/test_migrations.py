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


@pytest.mark.integration
def test_migration_upgrade_and_downgrade_on_postgres() -> None:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5433/signup_test",
    )
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
