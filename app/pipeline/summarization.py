"""요약 실행 오케스트레이션 (T-18, §2.1, §2.4, §3.4, US-05, US-08).

`LlmProvider` 인터페이스에만 의존하고 구체 구현(Ollama/Fake/무료 티어)을 알지 못한다
(§2.2 설계 원칙). 세션 상태를 `TRANSCRIBED→SUMMARIZING→DONE`(성공) 또는 `→FAILED`(실패)로
전이시키고 `summaries` 1건을 저장한다.

**전사 보존(US-08 핵심)**: 이 모듈은 `transcripts`/`transcript_segments`를 절대 읽기 전용
이상으로 건드리지 않는다 — 삭제·수정 로직이 아예 없다. 요약이 몇 번을 실패하든 전사는
그대로 남는다.

재시도 정책(§3.4): 429/5xx/타임아웃(`AppError(retryable=True)`)만 지수 백오프로 최대
`settings.LLM_MAX_RETRIES`회 시도한다. 형식 위반(`LLM_INVALID_RESPONSE`)이나 4xx는
`retryable=False`이므로 즉시 최종 실패로 처리된다 (형식 위반 자체의 1회 재요청은
`app/llm/summarizer.py`가 이미 수행했다 — 이 함수 관점에서는 "한 번의 시도"일 뿐이다).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.errors import AppError
from app.glossary.correction import correct_transcript_text, fetch_applicable_terms
from app.llm.base import LlmProvider
from app.llm.chunking import TimedSegment
from app.llm.map_reduce import summarize_transcript
from app.llm.parsing import render_markdown
from app.llm.schema import ParsedSummary
from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.pipeline.progress import clear_progress, set_progress

logger = logging.getLogger("app.pipeline.summarization")


def _persist_summary(
    db: DBSession, session: Session, provider: LlmProvider, parsed: ParsedSummary
) -> Summary:
    summary = Summary(
        session_id=session.id,
        content_markdown=render_markdown(parsed),
        key_points=[{"text": p.text, "atSeconds": p.at_seconds} for p in parsed.key_points],
        concepts=[{"term": c.term, "description": c.description} for c in parsed.concepts],
        code_snippets=[
            {"language": s.language, "code": s.code, "description": s.description}
            for s in parsed.code_snippets
        ],
        action_items=[{"text": a.text, "dueDate": a.due_date} for a in parsed.action_items],
        keywords=list(parsed.keywords),
        provider=provider.provider_name,
        provider_model=provider.provider_model,
    )
    db.add(summary)
    db.flush()
    return summary


def _build_timed_segments(
    db: DBSession, session: Session, transcript: Transcript
) -> list[TimedSegment]:
    """전사 세그먼트를 용어집으로 보정해 `TimedSegment` 목록으로 만든다 (§3.3, §3.4).

    각 세그먼트 텍스트에 T-23 용어 보정을 적용한다 — 저장된 `transcript_segments.text`
    자체는 원본 그대로 유지하고(T-23 결정 그대로), 요약 프롬프트에 넣을 때만 메모리상에서
    보정한다. 세그먼트가 하나도 없으면(예: 세그먼트 없이 텍스트만 있는 레거시/테스트 데이터)
    `text_corrected`/`text_raw`를 0초 시점의 세그먼트 1개로 취급해 폴백한다.
    """
    if transcript.segments:
        glossary_terms = fetch_applicable_terms(db, session.course)
        return [
            TimedSegment(
                start_seconds=segment.start_seconds,
                text=correct_transcript_text(segment.text, glossary_terms),
            )
            for segment in transcript.segments
        ]

    fallback_text = transcript.text_corrected or transcript.text_raw
    return [TimedSegment(start_seconds=0.0, text=fallback_text)] if fallback_text else []


def summarize_session(
    db: DBSession,
    session: Session,
    provider: LlmProvider,
    *,
    max_retries: int | None = None,
    backoff_base_seconds: float | None = None,
    sleep: Callable[[float], None] | None = None,
    chunk_size_tokens: int | None = None,
    chunk_overlap_tokens: int | None = None,
    map_call_interval_seconds: float | None = None,
) -> Session:
    """세션 전사를 요약하고 결과를 저장한다.

    Args:
        db: DB 세션. `flush()`까지만 하고 커밋은 호출부에 맡긴다 (`transcribe_session`과 동일
            관례).
        session: 요약 대상 세션 ORM 인스턴스. 전사(`transcripts`)가 이미 저장돼 있어야 한다.
        provider: 사용할 `LlmProvider` 구현체 (Fake 또는 실제 Ollama).
        max_retries: 429/5xx/타임아웃 재시도 최대 횟수. 미지정 시 `settings.LLM_MAX_RETRIES`.
        backoff_base_seconds: 지수 백오프 기준 지연(초). 미지정 시
            `settings.LLM_RETRY_BASE_DELAY_SECONDS`.
        sleep: 백오프 대기에 쓸 함수. 테스트에서 실제 대기를 건너뛰려면 `lambda _: None`을
            주입한다. 미지정 시 `time.sleep`.
        chunk_size_tokens: map-reduce(§3.4, T-21) 청크 크기(토큰 근사치). 미지정 시
            `settings.SUMMARY_CHUNK_SIZE_TOKENS`.
        chunk_overlap_tokens: 청크 간 오버랩(토큰 근사치). 미지정 시
            `settings.SUMMARY_CHUNK_OVERLAP_TOKENS`.
        map_call_interval_seconds: map 단계 청크 간 호출 간격(초). 미지정 시
            `settings.SUMMARY_MAP_CALL_INTERVAL_SECONDS`.

    Returns:
        갱신된 `session` (`DONE` 또는 `FAILED` 상태). 실패 시에도 예외를 던지지 않고
        `session.status="FAILED"` + `error_code`로 결과를 표현한다 (전사 오케스트레이션과
        동일한 관례).

    Raises:
        AppError("TRANSCRIPT_NOT_READY"): 전사가 아직 저장되지 않은 세션에 대해 호출된 경우.
            이 경우는 호출부의 사용 오류이므로 세션 상태를 건드리지 않고 즉시 던진다.
    """
    transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()
    if transcript is None:
        raise AppError("TRANSCRIPT_NOT_READY")

    effective_max_retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
    effective_backoff_base = (
        backoff_base_seconds
        if backoff_base_seconds is not None
        else settings.LLM_RETRY_BASE_DELAY_SECONDS
    )
    effective_sleep = sleep if sleep is not None else time.sleep
    effective_chunk_size_tokens = (
        chunk_size_tokens if chunk_size_tokens is not None else settings.SUMMARY_CHUNK_SIZE_TOKENS
    )
    effective_chunk_overlap_tokens = (
        chunk_overlap_tokens
        if chunk_overlap_tokens is not None
        else settings.SUMMARY_CHUNK_OVERLAP_TOKENS
    )
    effective_map_call_interval = (
        map_call_interval_seconds
        if map_call_interval_seconds is not None
        else settings.SUMMARY_MAP_CALL_INTERVAL_SECONDS
    )

    session.status = SessionStatus.SUMMARIZING.value
    session.error_code = None
    session.error_message = None
    db.flush()
    set_progress(session.id, stage=SessionStatus.SUMMARIZING.value, percent=0.0)

    timed_segments = _build_timed_segments(db, session, transcript)

    last_error: AppError | None = None
    for attempt in range(1, effective_max_retries + 1):
        try:
            parsed = summarize_transcript(
                provider,
                timed_segments,
                title=session.title,
                course=session.course,
                duration_seconds=session.duration_seconds,
                chunk_size_tokens=effective_chunk_size_tokens,
                overlap_tokens=effective_chunk_overlap_tokens,
                call_interval_seconds=effective_map_call_interval,
                sleep=effective_sleep,
            )
        except AppError as exc:
            last_error = exc
            logger.warning(
                "LLM summarization attempt failed: session_id=%s attempt=%d/%d code=%s "
                "retryable=%s",
                session.id,
                attempt,
                effective_max_retries,
                exc.code,
                exc.retryable,
            )
            if exc.retryable and attempt < effective_max_retries:
                effective_sleep(effective_backoff_base * (2 ** (attempt - 1)))
                continue
            break
        except Exception as exc:  # noqa: BLE001 — 어떤 예외든 요약 실패로 취급한다 (§2.4).
            last_error = AppError("LLM_FAILED", retryable=False)
            logger.warning(
                "LLM summarization attempt failed with unexpected error: session_id=%s "
                "attempt=%d/%d error_type=%s",
                session.id,
                attempt,
                effective_max_retries,
                type(exc).__name__,
            )
            break
        else:
            _persist_summary(db, session, provider, parsed)
            session.status = SessionStatus.DONE.value
            db.flush()
            logger.info(
                "LLM summarization succeeded: session_id=%s attempt=%d key_points=%d "
                "action_items=%d",
                session.id,
                attempt,
                len(parsed.key_points),
                len(parsed.action_items),
            )
            clear_progress(session.id)
            return session

    assert last_error is not None  # 루프가 continue 없이 빠져나오면 항상 설정되어 있다.
    session.status = SessionStatus.FAILED.value
    session.error_code = last_error.code
    session.error_message = last_error.message
    db.flush()
    clear_progress(session.id)
    return session
