"""세션 API (§5.3). 이번 범위(T-09)는 업로드 → 세션 생성만 다룬다.

`autoProcess`는 필드로만 받는다. 실제 전사·요약 파이프라인 연결(§2.1, US-02)은
그룹 C/D(T-19)에서 이어붙인다 — 지금은 업로드가 성공하면 항상 `status="UPLOADED"`로 응답한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session as DBSession

from app.audio.storage import delete_stored_file, save_upload_stream
from app.audio.validation import detect_audio_format, probe_audio, validate_duration_seconds
from app.core.errors import AppError
from app.db.session import get_db
from app.models.enums import SessionSource, SessionStatus
from app.models.session import Session as SessionModel
from app.schemas.session import SessionCreateResponse

router = APIRouter(tags=["sessions"])

# ③ GET /sessions/{id} 폴링 안내용 기본 간격 (§5.3 ①③).
DEFAULT_POLL_AFTER_SECONDS = 10


def _default_title(now: datetime) -> str:
    return f"{now:%Y-%m-%d} 수업"


@router.post("/sessions", status_code=201, response_model=SessionCreateResponse)
async def create_session(
    file: Annotated[UploadFile, File()],
    db: Annotated[DBSession, Depends(get_db)],
    title: Annotated[str | None, Form(max_length=200)] = None,
    course: Annotated[str | None, Form(max_length=100)] = None,
    autoProcess: Annotated[bool, Form()] = True,  # noqa: N803 (§5.1 camelCase 요청 필드)
) -> SessionCreateResponse:
    del autoProcess  # 이번 범위에서는 접수만 하고 실제 파이프라인 트리거는 하지 않는다.

    saved = await save_upload_stream(file)

    try:
        detected = detect_audio_format(saved.header)
        if detected is None:
            raise AppError("UNSUPPORTED_AUDIO_FORMAT")
        _format_key, mime_type = detected

        probe = probe_audio(saved.path)
        validate_duration_seconds(probe.duration_seconds)

        now = datetime.now(UTC)
        session = SessionModel(
            title=(title or "").strip() or _default_title(now),
            course=course,
            status=SessionStatus.UPLOADED.value,
            source=SessionSource.UPLOAD.value,
            audio_path=str(saved.path),
            original_filename=file.filename or "audio",
            mime_type=mime_type,
            file_size_bytes=saved.total_bytes,
            duration_seconds=probe.duration_seconds,
            recorded_at=now,
        )
        db.add(session)
        db.flush()
        db.refresh(session)
    except Exception:
        # §5.3 ①: 검증 실패 시 파일 미저장, 저장(DB) 실패 시 레코드·파일 모두 롤백.
        delete_stored_file(saved.path)
        raise

    return SessionCreateResponse(
        session_id=session.id,
        title=session.title,
        course=session.course,
        status=session.status,
        source=session.source,
        original_filename=session.original_filename,
        file_size_bytes=session.file_size_bytes,
        duration_seconds=session.duration_seconds,
        recorded_at=session.recorded_at,
        created_at=session.created_at,
        poll_after_seconds=DEFAULT_POLL_AFTER_SECONDS,
    )
