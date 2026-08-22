"""스트리밍 업로드 저장 유틸 단위 테스트 (T-08, §3.1).

핵심 검증 포인트:
- 저장 파일명은 항상 서버가 생성한 UUID 기반이다 (원본 파일명 미사용 → 경로 순회 차단).
- 업로드 바이트는 고정 크기 청크로 읽어 저장한다 (전체를 메모리에 적재하지 않는다).
- 누적 바이트가 한도를 넘으면 즉시(전체를 다 읽기 전에) 중단하고 부분 파일을 삭제한다.
- 디스크 여유 공간이 부족하면 저장을 시작하지 않는다.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from app.audio.storage import check_disk_space, save_upload_stream
from app.core.errors import AppError


class _FakeUploadFile:
    """실제 500MB를 메모리에 만들지 않고도 대용량 업로드를 흉내 내는 테스트 더블.

    `.read(size)` 호출마다 최대 `size` 바이트만 반환한다(실제 UploadFile과 동일 계약).
    `virtual_total_bytes`만큼 논리적으로 존재하는 것처럼 동작하되, 실제로는 매 호출마다
    `size` 바이트만 새로 만들어 반환하므로 프로세스 메모리에 전체를 들고 있지 않는다.
    """

    def __init__(self, virtual_total_bytes: int, header: bytes = b"RIFF") -> None:
        self.virtual_total_bytes = virtual_total_bytes
        self.header = header
        self.sent = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        remaining = self.virtual_total_bytes - self.sent
        if remaining <= 0:
            return b""
        take = min(size, remaining) if size and size > 0 else remaining
        chunk = (self.header + b"\x00" * take)[:take]
        self.sent += take
        return chunk


def test_check_disk_space_creates_dir_and_passes_when_enough_free(tmp_path: Path) -> None:
    target = tmp_path / "audio"
    check_disk_space(target)
    assert target.exists()
    # 0700 권한 (§3.7 data/ 디렉토리 소유자 전용)
    assert (target.stat().st_mode & 0o777) == 0o700


def test_check_disk_space_raises_when_free_space_below_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "audio"
    target.mkdir()

    fake_usage = shutil.disk_usage(target)._replace(free=1)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: fake_usage)

    with pytest.raises(AppError) as exc_info:
        check_disk_space(target)
    assert exc_info.value.code == "INSUFFICIENT_DISK_SPACE"


def test_save_upload_stream_uses_uuid_filename_not_original(tmp_path: Path) -> None:
    upload = _FakeUploadFile(virtual_total_bytes=1024, header=b"RIFF....WAVE")

    async def _run():
        return await save_upload_stream(upload, storage_dir=tmp_path, max_bytes=10_000)

    saved = asyncio.run(_run())

    assert saved.path.parent == tmp_path
    assert saved.total_bytes == 1024
    # 원본 파일명 등 사용자 입력 문자열이 저장 경로 어디에도 나타나지 않는다.
    assert "lecture" not in saved.path.name
    assert ".." not in saved.path.name
    assert "/" not in saved.path.name
    assert saved.path.exists()


def test_save_upload_stream_reads_in_bounded_chunks_not_whole_file(tmp_path: Path) -> None:
    # 논리적으로 200MB지만 실제로 한 번에 메모리에 올라가는 조각은 CHUNK_SIZE 이하여야 한다.
    virtual_size = 200 * 1024 * 1024
    upload = _FakeUploadFile(virtual_total_bytes=virtual_size)

    async def _run():
        return await save_upload_stream(upload, storage_dir=tmp_path, max_bytes=virtual_size + 1)

    saved = asyncio.run(_run())

    assert saved.total_bytes == virtual_size
    assert all(0 < n <= 1024 * 1024 for n in upload.read_sizes if n > 0)
    assert len(upload.read_sizes) > 10  # 한 번에 다 읽지 않고 여러 청크로 나눠 읽었다


def test_save_upload_stream_aborts_early_when_exceeding_max_bytes(tmp_path: Path) -> None:
    # 가상 크기가 아주 커도(2GB) max_bytes를 넘는 순간 즉시 중단해야 한다.
    upload = _FakeUploadFile(virtual_total_bytes=2 * 1024 * 1024 * 1024)
    max_bytes = 5 * 1024 * 1024  # 5MB

    async def _run():
        await save_upload_stream(upload, storage_dir=tmp_path, max_bytes=max_bytes)

    with pytest.raises(AppError) as exc_info:
        asyncio.run(_run())
    assert exc_info.value.code == "FILE_TOO_LARGE"

    # 초과 시점까지만 읽고 중단했어야 한다 (전체 2GB를 다 읽지 않음).
    assert upload.sent <= max_bytes + (1024 * 1024)
    # 부분 파일이 남아있지 않아야 한다 (실패 시 저장 안 됨).
    assert list(tmp_path.iterdir()) == []


def test_save_upload_stream_creates_storage_dir_with_owner_only_permission(
    tmp_path: Path,
) -> None:
    storage_dir = tmp_path / "nested" / "audio"
    upload = _FakeUploadFile(virtual_total_bytes=10)

    async def _run():
        return await save_upload_stream(upload, storage_dir=storage_dir, max_bytes=10_000)

    asyncio.run(_run())
    assert (storage_dir.stat().st_mode & 0o777) == 0o700


def test_save_upload_stream_rejects_empty_file(tmp_path: Path) -> None:
    upload = _FakeUploadFile(virtual_total_bytes=0)

    async def _run():
        await save_upload_stream(upload, storage_dir=tmp_path, max_bytes=10_000)

    with pytest.raises(AppError) as exc_info:
        asyncio.run(_run())
    assert exc_info.value.code == "INVALID_AUDIO_FILE"
    assert list(tmp_path.iterdir()) == []
