"""운영 SQLite 백업(app/core/backup.py) 단위 테스트 (2026-10-18)."""

from __future__ import annotations

import os
import sqlite3
import time

import pytest

from app.core.backup import backup_sqlite, sqlite_path_from_url


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    conn.commit()
    conn.close()


def test_backup_copies_all_rows_and_mirrors(tmp_path):
    src = tmp_path / "src.db"
    _make_db(src)

    target = backup_sqlite(
        src, reason="daily", local_dir=tmp_path / "local", mirror_dir=tmp_path / "mirror"
    )

    assert target.name.endswith("-daily.db")
    assert sqlite3.connect(target).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    assert (tmp_path / "mirror" / target.name).exists()
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_backup_prunes_copies_older_than_retention(tmp_path):
    src = tmp_path / "src.db"
    _make_db(src)
    local = tmp_path / "local"
    local.mkdir()
    old = local / "lecture_notes-20200101-000000-daily.db"
    old.write_bytes(b"")
    stale = time.time() - 15 * 86400
    os.utime(old, (stale, stale))
    unrelated = local / "keep-me.db"
    unrelated.write_bytes(b"")
    os.utime(unrelated, (stale, stale))

    backup_sqlite(src, reason="daily", local_dir=local, mirror_dir=None, retention_days=14)

    assert not old.exists()
    assert unrelated.exists()


def test_backup_survives_mirror_failure(tmp_path):
    src = tmp_path / "src.db"
    _make_db(src)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")

    target = backup_sqlite(src, reason="daily", local_dir=tmp_path / "local", mirror_dir=blocker)

    assert target.exists()


def test_backup_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_sqlite(tmp_path / "nope.db", reason="daily", local_dir=tmp_path, mirror_dir=None)


@pytest.mark.parametrize(
    ("url", "is_sqlite"),
    [
        ("sqlite:///./data/lecture_notes.db", True),
        ("sqlite:////abs/path.db", True),
        ("sqlite:///:memory:", False),
        ("postgresql+psycopg2://u:p@localhost:5433/db", False),
    ],
)
def test_sqlite_path_from_url(url, is_sqlite):
    path = sqlite_path_from_url(url)
    assert (path is not None) == is_sqlite
    if path is not None:
        assert path.is_absolute()
