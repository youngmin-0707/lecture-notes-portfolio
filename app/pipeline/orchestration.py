"""전사 → 요약 파이프라인 오케스트레이션 (T-19, §2.1, US-02).

`POST /api/v1/sessions/{id}/process`(§5.3②)가 `run_pipeline_in_background()`를
`BackgroundTasks`로 예약한다. 요청-응답 흐름의 DB 세션은 응답이 나간 뒤 이미 닫혀 있으므로,
백그라운드 작업은 자신만의 새 DB 세션(`SessionLocal()`)을 연다.

**"전사가 이미 있으면 요약만"(§2.4) 규칙**: `run_pipeline()`은 세션에 이미 `transcripts` 행이
있으면 전사 단계를 건너뛰고 곧바로 요약으로 진행한다. 이는 재실행(§2.4 "재실행" 화살표)뿐
아니라 복구 스윕(T-20) 이후 재시도에도 동일하게 적용된다 — 전사를 다시 돌리는 것은 순수한
낭비라는 §3.6 원칙을 그대로 따른다.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db.session import SessionLocal
from app.models.enums import QuizStatus, SessionStatus
from app.models.quiz import Quiz
from app.models.session import Session
from app.models.transcript import Transcript
from app.pipeline.providers import build_llm_provider, build_stt_provider
from app.pipeline.quiz import generate_quiz
from app.pipeline.summarization import summarize_session
from app.pipeline.transcription import transcribe_session

logger = logging.getLogger("app.pipeline.orchestration")


def run_pipeline(
    db: DBSession,
    session: Session,
    *,
    stt_model: str | None = None,
    llm_provider_name: str | None = None,
    skip_summary: bool = False,
) -> Session:
    """세션을 전사→요약까지 동기적으로 실행한다 (백그라운드 작업의 실제 본체).

    전사가 이미 저장되어 있으면(§2.4) 전사 단계를 건너뛰고 요약부터 재개한다.
    """
    existing_transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()

    if existing_transcript is None:
        stt_provider = build_stt_provider(stt_model)
        session = transcribe_session(db, session, stt_provider)
        if session.status != SessionStatus.TRANSCRIBED.value:
            # STT 실패 — FAILED 상태로 이미 기록됨. 요약으로 진행하지 않는다.
            return session
    else:
        logger.info(
            "run_pipeline: existing transcript found, skipping STT: session_id=%s", session.id
        )
        session.status = SessionStatus.TRANSCRIBED.value
        session.error_code = None
        session.error_message = None
        db.flush()

    if skip_summary:
        return session

    llm_provider = build_llm_provider(llm_provider_name)
    return summarize_session(db, session, llm_provider)


def run_pipeline_in_background(
    session_id: str,
    *,
    stt_model: str | None = None,
    llm_provider_name: str | None = None,
    skip_summary: bool = False,
) -> None:
    """`BackgroundTasks` 진입점. 요청 스코프와 분리된 새 DB 세션을 열고 커밋까지 책임진다."""
    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        if session is None:
            logger.warning("run_pipeline_in_background: session not found id=%s", session_id)
            return
        run_pipeline(
            db,
            session,
            stt_model=stt_model,
            llm_provider_name=llm_provider_name,
            skip_summary=skip_summary,
        )
        db.commit()
    except Exception:
        # `run_pipeline()`이 처리하는 실패는 이미 session.status="FAILED"로 커밋 대기 중이므로
        # 여기 도달하는 예외는 예상치 못한 버그다. 그래도 세션이 TRANSCRIBING/SUMMARIZING에
        # 멈춰 있지 않도록 최선을 다해 FAILED로 남긴다 (다음 서버 재기동을 기다리지 않아도 되게).
        db.rollback()
        logger.exception(
            "run_pipeline_in_background: unexpected failure, session_id=%s", session_id
        )
        _mark_failed_after_crash(session_id)
    finally:
        db.close()


def resummarize_session_in_background(
    session_id: str, *, llm_provider_name: str | None = None
) -> None:
    """`BackgroundTasks` 진입점 — 요약만 다시 실행한다 (T-25, US-17, §5.3⑥).

    `run_pipeline_in_background()`와 달리 전사 상태를 전혀 건드리지 않는다. 전사가 이미
    저장돼 있어야 한다는 전제(§2.4 "재실행" 규칙)는 라우터가 요청을 받는 시점에
    `TRANSCRIPT_NOT_READY`로 이미 검증했다.
    """
    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        if session is None:
            logger.warning("resummarize_session_in_background: session not found id=%s", session_id)
            return
        llm_provider = build_llm_provider(llm_provider_name)
        summarize_session(db, session, llm_provider)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "resummarize_session_in_background: unexpected failure, session_id=%s", session_id
        )
        _mark_failed_after_crash(session_id)
    finally:
        db.close()


def generate_quiz_in_background(
    session_id: str, quiz_id: str, *, llm_provider_name: str | None = None
) -> None:
    """`BackgroundTasks` 진입점 — 복습 문제를 생성한다 (2026-09-01, §5.3⑫).

    라우터가 이미 `quiz.status=GENERATING`으로 저장해 둔 행(`quiz_id`)을 찾아 채운다.
    """
    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        quiz = db.get(Quiz, quiz_id)
        if session is None or quiz is None:
            logger.warning(
                "generate_quiz_in_background: session or quiz not found session_id=%s quiz_id=%s",
                session_id,
                quiz_id,
            )
            return
        llm_provider = build_llm_provider(llm_provider_name)
        generate_quiz(db, session, quiz, llm_provider)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "generate_quiz_in_background: unexpected failure, session_id=%s quiz_id=%s",
            session_id,
            quiz_id,
        )
        _mark_quiz_failed_after_crash(quiz_id)
    finally:
        db.close()


def _mark_quiz_failed_after_crash(quiz_id: str) -> None:
    recovery_db = SessionLocal()
    try:
        quiz = recovery_db.get(Quiz, quiz_id)
        if quiz is not None and quiz.status == QuizStatus.GENERATING.value:
            quiz.status = QuizStatus.FAILED.value
            quiz.error_code = "INTERNAL_ERROR"
            quiz.error_message = "복습 문제 생성 중 예기치 못한 오류가 발생했습니다."
            recovery_db.commit()
    except Exception:
        recovery_db.rollback()
        logger.exception(
            "generate_quiz_in_background: failed to mark quiz FAILED after crash, quiz_id=%s",
            quiz_id,
        )
    finally:
        recovery_db.close()


def _mark_failed_after_crash(session_id: str) -> None:
    recovery_db = SessionLocal()
    try:
        session = recovery_db.get(Session, session_id)
        if session is not None and session.status in (
            SessionStatus.TRANSCRIBING.value,
            SessionStatus.SUMMARIZING.value,
        ):
            session.status = SessionStatus.FAILED.value
            session.error_code = "INTERNAL_ERROR"
            session.error_message = "처리 중 예기치 못한 오류가 발생했습니다."
            recovery_db.commit()
    except Exception:
        recovery_db.rollback()
        logger.exception(
            "run_pipeline_in_background: failed to mark session FAILED after crash, session_id=%s",
            session_id,
        )
    finally:
        recovery_db.close()
