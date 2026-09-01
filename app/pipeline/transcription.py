"""전사 실행 오케스트레이션 (T-12, §2.1, §2.4, US-04).

`SttProvider` 인터페이스에만 의존하고 구체 구현(로컬 Whisper/Fake/무료 티어)을 알지
못한다 (§2.2 설계 원칙). 세션 상태를 `UPLOADED→TRANSCRIBING→TRANSCRIBED`(성공) 또는
`→FAILED`(실패)로 전이시키고 `transcripts` 1건과 `transcript_segments` N건을 저장한다.

이번 라운드에서는 동기 호출만 지원한다. `POST /sessions/{id}/process`를 통한 비동기
트리거(`BackgroundTasks`)는 T-19에서 연결한다.

**동시 전사 제한(2026-08-30)**: 업로드를 짧은 시간 안에 여러 건 올리면 `BackgroundTasks`가
전부 동시에(별도 스레드로) 실행돼, CPU 바운드인 로컬 Whisper 추론이 서로 코어를 다투게 된다
— 실사용 중 강의 9개를 거의 동시에 올렸더니 4시간 동안 전체 진행률이 20% 안팎에 머무는 걸
실측했다(단독 실행 시 실시간의 약 5배 속도가 나오던 것과 대비). `_TRANSCRIPTION_SEMAPHORE`로
동시 실행 개수를 `settings.MAX_CONCURRENT_TRANSCRIPTIONS`(기본 1, 순차 처리)로 제한해
해결한다 — 업로드는 몇 개를 연달아 해도 즉시 다 접수되고 큐에 쌓이듯 순서대로 처리된다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.errors import AppError
from app.glossary.correction import (
    build_initial_prompt,
    correct_transcript_text,
    fetch_applicable_terms,
)
from app.models.enums import SessionStatus
from app.models.glossary import GlossaryTerm
from app.models.session import Session
from app.models.transcript import Transcript, TranscriptSegment
from app.pipeline.progress import clear_progress, make_stt_progress_callback, set_progress
from app.stt.base import SttProvider, SttSegment, SttTranscriptionResult

logger = logging.getLogger("app.pipeline.transcription")

# CPU 바운드인 로컬 Whisper 추론이 동시에 여러 개 돌면 서로 코어를 다퉈 전체적으로 훨씬
# 느려진다(모듈 docstring 참고) — 프로세스 전역으로 동시 실행 개수를 제한한다.
_TRANSCRIPTION_SEMAPHORE = threading.Semaphore(settings.MAX_CONCURRENT_TRANSCRIPTIONS)


def _validate_segments_monotonic_non_overlapping(segments: Sequence[SttSegment]) -> None:
    """US-04: 세그먼트 시작 시각이 단조 증가하고 서로 겹치지 않아야 한다.

    Provider가 이 불변식을 어기면 결과를 저장하지 않고 실패시킨다 — 잘못된 세그먼트를
    조용히 저장하면 "세그먼트 클릭 시 해당 시점 재생" 같은 후속 기능이 깨진다.
    """
    previous_end: float | None = None
    for segment in segments:
        if segment.end < segment.start:
            raise AppError("STT_FAILED", message="전사 세그먼트 구간이 올바르지 않습니다.")
        if previous_end is not None and segment.start < previous_end:
            raise AppError("STT_FAILED", message="전사 세그먼트가 시간 순서를 위반했습니다.")
        previous_end = segment.end


def _persist_transcript(
    db: DBSession,
    session: Session,
    provider: SttProvider,
    result: SttTranscriptionResult,
    glossary_terms: Sequence[GlossaryTerm],
) -> None:
    transcript = Transcript(
        session_id=session.id,
        text_raw=result.text,
        # 원본과 보정본을 둘 다 보존한다 (§3.3) — 용어집 치환이 오작동해도 원본으로 되돌릴 수
        # 있어야 한다. 용어집이 비어 있으면 보정본은 원본과 동일하다.
        text_corrected=correct_transcript_text(result.text, glossary_terms),
        language=result.language,
        provider=provider.provider_name,
        provider_model=provider.provider_model,
        elapsed_seconds=result.elapsed_seconds,
    )
    db.add(transcript)
    db.flush()

    for seq, segment in enumerate(result.segments):
        db.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                seq=seq,
                start_seconds=segment.start,
                end_seconds=segment.end,
                text=segment.text,
            )
        )
    db.flush()


def transcribe_session(
    db: DBSession,
    session: Session,
    provider: SttProvider,
    *,
    initial_prompt: str | None = None,
) -> Session:
    """세션 오디오를 전사하고 결과를 저장한다.

    Args:
        db: DB 세션. 이 함수는 `flush()`까지만 하고 커밋은 호출부(라우터 또는 `get_db`)에
            맡긴다 (`POST /sessions`와 동일한 관례).
        session: 전사 대상 세션 ORM 인스턴스 (보통 `UPLOADED` 상태).
        provider: 사용할 `SttProvider` 구현체 (Fake 또는 실제 엔진).
        initial_prompt: 명시하면 이 값을 그대로 쓴다 (주로 테스트용). 생략(`None`)하면
            `session.course`에 해당하는 용어집(§3.3)으로 자동 생성한다.

    Returns:
        갱신된 `session` (`TRANSCRIBED` 또는 `FAILED` 상태). 실패 시에도 예외를 던지지
        않고 `session.status="FAILED"` + `error_code`로 결과를 표현한다 — 호출부(향후
        파이프라인 오케스트레이션)가 요약 등 다음 단계로 넘어갈지 판단하기 쉽게 하기 위함.
    """
    session.status = SessionStatus.TRANSCRIBING.value
    session.error_code = None
    session.error_message = None
    db.flush()

    set_progress(session.id, stage=SessionStatus.TRANSCRIBING.value, percent=0.0)
    progress_callback = make_stt_progress_callback(
        session.id, stage=SessionStatus.TRANSCRIBING.value
    )

    glossary_terms = fetch_applicable_terms(db, session.course)
    if initial_prompt is None:
        initial_prompt = build_initial_prompt(glossary_terms)

    try:
        with _TRANSCRIPTION_SEMAPHORE:
            result = provider.transcribe(
                session.audio_path,
                language=settings.STT_LANGUAGE,
                initial_prompt=initial_prompt,
                progress_callback=progress_callback,
            )
        _validate_segments_monotonic_non_overlapping(result.segments)
        _persist_transcript(db, session, provider, result, glossary_terms)
    except Exception as exc:  # noqa: BLE001 — 어떤 예외든 STT 실패로 취급한다 (§2.4).
        code = exc.code if isinstance(exc, AppError) else "STT_FAILED"
        message = exc.message if isinstance(exc, AppError) else "전사에 실패했습니다."
        logger.warning(
            "STT failed: session_id=%s code=%s error_type=%s",
            session.id,
            code,
            type(exc).__name__,
        )
        session.status = SessionStatus.FAILED.value
        session.error_code = code
        session.error_message = message
        db.flush()
        clear_progress(session.id)
        return session

    session.status = SessionStatus.TRANSCRIBED.value
    db.flush()

    logger.info(
        "STT succeeded: session_id=%s elapsed_seconds=%.2f segment_count=%d text_length=%d",
        session.id,
        result.elapsed_seconds,
        len(result.segments),
        len(result.text),
    )

    clear_progress(session.id)
    return session
