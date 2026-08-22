"""스트리밍 업로드 저장 (§3.1).

- 용량 검사는 스트리밍 중 누적 바이트로 한다 (전체를 메모리에 올리지 않는다).
- 저장 경로는 서버가 생성한 UUID 기반으로만 만든다. 원본 파일명은 어디에도 쓰지 않는다
  (경로 순회 취약점 원천 차단).
- 저장 전 디스크 여유 공간을 확인한다.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.audio.validation import MAGIC_HEADER_SIZE
from app.core.config import settings
from app.core.errors import AppError
from app.core.fs import ensure_private_dir

# 한 번에 메모리에 올리는 최대 바이트 수. 500MB 파일이라도 이 크기 이상은 절대 한 번에
# 읽지 않는다 (§3.1, §6 메모리 NFR).
CHUNK_SIZE = 1024 * 1024  # 1MB


class _AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    total_bytes: int
    header: bytes


def check_disk_space(storage_dir: Path) -> None:
    """저장 디렉토리를 준비하고(없으면 소유자 전용 권한으로 생성) 여유 공간을 확인한다."""
    ensure_private_dir(storage_dir)

    usage = shutil.disk_usage(storage_dir)
    if usage.free < settings.MIN_DISK_FREE_BYTES:
        raise AppError("INSUFFICIENT_DISK_SPACE")


async def save_upload_stream(
    upload: _AsyncReadable,
    *,
    storage_dir: Path | None = None,
    max_bytes: int | None = None,
) -> SavedUpload:
    """업로드를 청크 단위로 읽어 디스크에 저장한다.

    반환값의 `header`는 매직 넘버 판별에 필요한 앞부분 바이트다 (`app.audio.validation`).
    한도를 초과하거나 내용이 비어 있으면 `AppError`를 던지고 부분 저장 파일을 정리한다.
    """
    storage_dir = storage_dir if storage_dir is not None else Path(settings.AUDIO_STORAGE_DIR)
    max_bytes = max_bytes if max_bytes is not None else settings.MAX_UPLOAD_SIZE_BYTES

    check_disk_space(storage_dir)

    dest = storage_dir / f"{uuid.uuid4().hex}.upload"
    total = 0
    header = b""

    try:
        with dest.open("wb") as out:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if len(header) < MAGIC_HEADER_SIZE:
                    header += chunk[: MAGIC_HEADER_SIZE - len(header)]
                if total > max_bytes:
                    raise AppError("FILE_TOO_LARGE")
                out.write(chunk)

        if total == 0:
            raise AppError("INVALID_AUDIO_FILE")
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    return SavedUpload(path=dest, total_bytes=total, header=header)


def delete_stored_file(path: Path | str) -> None:
    """저장된 업로드 파일을 삭제한다 (검증 실패 롤백, 세션 삭제 등에서 사용)."""
    Path(path).unlink(missing_ok=True)
