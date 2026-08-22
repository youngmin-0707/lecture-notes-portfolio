"""세션 API (§5.3). 이번 범위(T-09)는 업로드 → 세션 생성만 다룬다.

`autoProcess`는 필드로만 받는다. 실제 전사·요약 파이프라인 연결(§2.1, US-02)은
그룹 C/D(T-19)에서 이어붙인다 — 지금은 업로드가 성공하면 항상 `status="UPLOADED"`로 응답한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.audio.storage import delete_stored_file, save_upload_stream
from app.audio.validation import detect_audio_format, probe_audio, validate_duration_seconds
from app.core.errors import AppError
from app.db.session import get_db
from app.models.enums import SessionSource, SessionStatus
from app.models.session import Session as SessionModel
from app.models.transcript import Transcript
from app.pipeline.progress import ProgressInfo, get_progress
from app.schemas.session import (
    ProgressResponse,
    SessionCreateResponse,
    SessionDetailResponse,
    TranscriptDetailResponse,
    TranscriptInfoResponse,
    TranscriptSegmentResponse,
)

router = APIRouter(tags=["sessions"])

# 처리 중(TRANSCRIBING/SUMMARIZING) 상태에서 진행률 스토어에 값이 없을 때 쓰는 기본값.
_PROCESSING_STATUSES = {SessionStatus.TRANSCRIBING.value, SessionStatus.SUMMARIZING.value}

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


def _get_session_or_404(db: DBSession, session_id: str) -> SessionModel:
    session = db.get(SessionModel, session_id)
    if session is None:
        raise AppError("SESSION_NOT_FOUND")
    return session


def _resolve_progress(session: SessionModel) -> ProgressInfo | None:
    if session.status not in _PROCESSING_STATUSES:
        return None
    stored = get_progress(session.id)
    if stored is not None:
        return stored
    # 스토어에 값이 없을 수 있다 (예: 서버 재시작 직후, 또는 상태만 수동으로 맞춘 테스트).
    return ProgressInfo(stage=session.status, percent=0.0, eta_seconds=None)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db)],
) -> SessionDetailResponse:
    """세션 상세 조회 (§5.3③). 처리 실패(FAILED)여도 HTTP 200을 반환한다."""
    session = _get_session_or_404(db, session_id)

    transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()

    if transcript is not None:
        text = transcript.text_corrected or transcript.text_raw
        transcript_info = TranscriptInfoResponse(
            available=True,
            provider=transcript.provider,
            provider_model=transcript.provider_model,
            character_count=len(text),
            elapsed_seconds=transcript.elapsed_seconds,
        )
    else:
        transcript_info = TranscriptInfoResponse(available=False)

    progress = _resolve_progress(session)
    progress_response = (
        ProgressResponse(
            stage=progress.stage, percent=progress.percent, eta_seconds=progress.eta_seconds
        )
        if progress is not None
        else None
    )

    return SessionDetailResponse(
        session_id=session.id,
        title=session.title,
        course=session.course,
        status=session.status,
        duration_seconds=session.duration_seconds,
        recorded_at=session.recorded_at,
        error_code=session.error_code,
        error_message=session.error_message,
        progress=progress_response,
        poll_after_seconds=DEFAULT_POLL_AFTER_SECONDS if progress is not None else None,
        transcript=transcript_info,
        summary=None,
    )


@router.get("/sessions/{session_id}/transcript", response_model=TranscriptDetailResponse)
def get_session_transcript(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db)],
    corrected: bool = True,
) -> TranscriptDetailResponse:
    """전사 전문 + 세그먼트 조회 (§5.3④, US-04).

    `corrected=true`(기본)를 요청해도 아직 `text_corrected`가 채워지지 않았다면
    (용어집 보정은 그룹 E/T-23) `text_raw`로 폴백한다.
    """
    session = _get_session_or_404(db, session_id)

    transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()
    if transcript is None:
        raise AppError("TRANSCRIPT_NOT_READY")

    used_corrected = corrected and transcript.text_corrected is not None
    text = transcript.text_corrected if used_corrected else transcript.text_raw

    segments = [
        TranscriptSegmentResponse(
            seq=segment.seq,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            text=segment.text,
        )
        for segment in sorted(transcript.segments, key=lambda s: s.seq)
    ]

    return TranscriptDetailResponse(
        session_id=session.id,
        language=transcript.language,
        corrected=used_corrected,
        text=text,
        segments=segments,
    )
