"""데이터 디렉토리/파일 권한 테스트 (T-38, §3.7 "data/는 소유자 전용 권한(0700)").

T-38 보안 점검 중 실제로 `data/`가 0755, `data/lecture_notes.db`가 0644(월드 리더블)로
새고 있던 걸 발견했다 — `mkdir(mode=...)`는 디렉토리가 이미 있으면 그 인자를 무시하기
때문이다. 이 테스트는 "이미 잘못된 권한으로 존재하는 경로"를 만들어두고, 우리 코드가 그걸
스스로 고치는지(단순히 최초 생성 시에만 맞는 게 아니라) 검증한다.
"""

from __future__ import annotations

import stat
from pathlib import Path

from app.audio.storage import check_disk_space
from app.core.fs import ensure_private_dir, ensure_private_file
from app.db.session import _build_engine


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestEnsurePrivateDir:
    def test_creates_missing_dir_with_0700(self, tmp_path: Path) -> None:
        target = tmp_path / "new_dir"

        ensure_private_dir(target)

        assert target.is_dir()
        assert _mode(target) == 0o700

    def test_fixes_existing_dir_with_wrong_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "existing_dir"
        target.mkdir(mode=0o755)
        target.chmod(0o755)  # mkdir의 mode도 umask 영향을 받을 수 있어 확실히 굳힌다.
        assert _mode(target) == 0o755

        ensure_private_dir(target)

        assert _mode(target) == 0o700

    def test_creates_nested_parents(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c"

        ensure_private_dir(target)

        assert target.is_dir()
        assert _mode(target) == 0o700


class TestEnsurePrivateFile:
    def test_fixes_existing_file_with_wrong_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "secret.db"
        target.write_text("data")
        target.chmod(0o644)
        assert _mode(target) == 0o644

        ensure_private_file(target)

        assert _mode(target) == 0o600

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        target = tmp_path / "does-not-exist.db"

        ensure_private_file(target)  # 예외 없이 조용히 넘어가야 한다.

        assert not target.exists()


class TestSqliteEngineEnforcesPrivatePermissions:
    def test_fresh_db_gets_private_dir_and_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "lecture_notes.db"
        engine = _build_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect():
                pass  # 연결 시점에 sqlite가 파일을 실제로 만든다.

            assert _mode(db_path.parent) == 0o700
            assert db_path.exists()
            assert _mode(db_path) == 0o600
        finally:
            engine.dispose()

    def test_existing_db_with_wrong_permissions_gets_fixed_on_connect(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lecture_notes.db"
        db_path.write_text("")  # 파일이 미리 잘못된 권한으로 있었던 상황을 흉내낸다.
        db_path.chmod(0o644)
        tmp_path.chmod(0o755)

        engine = _build_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect():
                pass

            assert _mode(db_path) == 0o600
        finally:
            engine.dispose()


class TestAudioStorageDirPermissions:
    def test_check_disk_space_fixes_existing_wrong_permission_dir(self, tmp_path: Path) -> None:
        storage_dir = tmp_path / "audio"
        storage_dir.mkdir(mode=0o755)
        storage_dir.chmod(0o755)

        check_disk_space(storage_dir)

        assert _mode(storage_dir) == 0o700
