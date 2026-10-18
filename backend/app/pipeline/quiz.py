"""복습 문제 생성 오케스트레이션 (2026-09-01 신규, 복습 문제 자동 생성 기능).

`app/pipeline/summarization.py`와 대칭 구조지만 훨씬 단순하다 — map-reduce 없이 항상
단일 LLM 호출이다(근거 자료가 이미 정리된 요약 본문이라 청크가 필요할 만큼 길지 않다고
보고, `app/llm/quiz_prompt.py`에서 그대로 한 번에 넘긴다).

재시도 정책은 요약과 동일하다(§3.4): 429/5xx/타임아웃만 지수 백오프로 재시도하고, 형식
위반이나 4xx는 즉시 최종 실패로 처리한다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.errors import AppError
from app.llm.base import LlmProvider
from app.llm.quiz_generator import generate_structured_quiz
from app.llm.quiz_prompt import build_quiz_prompt
from app.models.enums import QuizStatus
from app.models.quiz import Quiz
from app.models.session import Session
from app.models.summary import Summary

logger = logging.getLogger("app.pipeline.quiz")


def generate_quiz(
    db: DBSession,
    session: Session,
    quiz: Quiz,
    provider: LlmProvider,
    *,
    max_retries: int | None = None,
    backoff_base_seconds: float | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Quiz:
    """세션의 최신 요약(자유형식 본문)을 근거로 복습 문제를 생성해 `quiz`에 채운다.

    Args:
        db: DB 세션. `flush()`까지만 하고 커밋은 호출부에 맡긴다(`summarize_session`과
            동일 관례).
        quiz: 호출부가 미리 `status=GENERATING`으로 저장해 둔 대상 행 — API가 202 응답을
            내는 시점에 이미 존재해야 프론트가 곧바로 폴링을 시작할 수 있다(`session.status`를
            먼저 `SUMMARIZING`으로 바꿔두는 요약 파이프라인과 동일한 이유).

    Returns:
        갱신된 `quiz` (`DONE` 또는 `FAILED` 상태). 실패 시에도 예외를 던지지 않고
        `quiz.status="FAILED"` + `error_code`로 결과를 표현한다.

    Raises:
        AppError("SUMMARY_NOT_READY"): 세션에 (본문이 있는) 요약이 아직 없는 경우. 호출부의
            사용 오류이므로 `quiz` 상태를 건드리지 않고 즉시 던진다 — 라우터가 애초에
            사전 검증하므로 정상 흐름에서는 도달하지 않는 방어적 재검증이다.
    """
    latest_summary = db.execute(
        select(Summary)
        .where(Summary.session_id == session.id)
        .order_by(Summary.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_summary is None or not latest_summary.detailed_notes_markdown.strip():
        raise AppError("SUMMARY_NOT_READY")

    effective_max_retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES
    effective_backoff_base = (
        backoff_base_seconds
        if backoff_base_seconds is not None
        else settings.LLM_RETRY_BASE_DELAY_SECONDS
    )
    effective_sleep = sleep if sleep is not None else time.sleep

    prompt = build_quiz_prompt(
        latest_summary.detailed_notes_markdown,
        title=session.title,
        course=session.course,
    )

    last_error: AppError | None = None
    for attempt in range(1, effective_max_retries + 1):
        try:
            parsed = generate_structured_quiz(provider, prompt)
        except AppError as exc:
            last_error = exc
            logger.warning(
                "LLM quiz generation attempt failed: session_id=%s attempt=%d/%d code=%s "
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
        except Exception as exc:  # noqa: BLE001 — 어떤 예외든 생성 실패로 취급한다 (§2.4 원칙).
            last_error = AppError("LLM_FAILED", retryable=False)
            logger.warning(
                "LLM quiz generation attempt failed with unexpected error: session_id=%s "
                "attempt=%d/%d error_type=%s",
                session.id,
                attempt,
                effective_max_retries,
                type(exc).__name__,
            )
            break
        else:
            quiz.status = QuizStatus.DONE.value
            quiz.questions = [
                {"question": q.question, "answer": q.answer} for q in parsed.questions
            ]
            quiz.provider = provider.provider_name
            quiz.provider_model = provider.provider_model
            quiz.error_code = None
            quiz.error_message = None
            db.flush()
            logger.info(
                "LLM quiz generation succeeded: session_id=%s attempt=%d question_count=%d",
                session.id,
                attempt,
                len(parsed.questions),
            )
            return quiz

    assert last_error is not None  # 루프가 continue 없이 빠져나오면 항상 설정되어 있다.
    quiz.status = QuizStatus.FAILED.value
    quiz.error_code = last_error.code
    quiz.error_message = last_error.message
    db.flush()
    return quiz
