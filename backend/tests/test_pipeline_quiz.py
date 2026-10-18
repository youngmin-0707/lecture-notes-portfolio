"""복습 문제 생성 오케스트레이션 테스트 (2026-09-01, 복습 문제 자동 생성 기능).

`tests/test_pipeline_summarization.py`와 대칭 구조다. Fake `LlmProvider`로 실제 LLM 없이
상태 전이·저장·재시도 로직을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.llm.fake import DEFAULT_VALID_QUIZ_JSON, FakeLlmProvider, make_quiz_json
from app.models.enums import QuizStatus, SessionStatus
from app.models.quiz import Quiz
from app.models.session import Session
from app.models.summary import Summary
from app.pipeline.quiz import generate_quiz


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status=SessionStatus.DONE.value,
        source="UPLOAD",
        audio_path=None,
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=3600.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


_DEFAULT_DETAILED_NOTES = "1. 이진 탐색 트리(BST)\n정의와 삽입 연산."


def _add_summary(
    db_session, session: Session, *, detailed_notes: str | None = _DEFAULT_DETAILED_NOTES
) -> Summary:
    summary = Summary(
        session_id=session.id,
        content_markdown="## 한 줄 요약\n이진 탐색 트리 강의입니다.",
        key_points=[],
        keywords=[],
        detailed_notes_markdown=detailed_notes if detailed_notes is not None else "",
        provider="fake",
        provider_model="fake-large",
    )
    db_session.add(summary)
    db_session.flush()
    return summary


def _make_quiz(db_session, session: Session) -> Quiz:
    quiz = Quiz(session_id=session.id, status=QuizStatus.GENERATING.value)
    db_session.add(quiz)
    db_session.flush()
    return quiz


def _no_sleep(_seconds: float) -> None:
    """백오프 재시도 테스트가 실제로 기다리지 않도록 주입하는 sleep 대체 함수."""


class TestSuccessfulQuizGeneration:
    def test_transitions_to_done_and_saves_questions(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(responses=[DEFAULT_VALID_QUIZ_JSON], provider_model="fake-llm")
        result = generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)

        assert result.status == QuizStatus.DONE.value
        assert result.error_code is None
        assert len(result.questions) >= 1
        assert all("question" in q and "answer" in q for q in result.questions)

        stored = db_session.execute(select(Quiz).where(Quiz.id == quiz.id)).scalar_one()
        assert stored.status == QuizStatus.DONE.value
        assert stored.provider == "fake"
        assert stored.provider_model == "fake-llm"

    def test_prompt_grounded_on_detailed_notes(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session, detailed_notes="RAG와 PGVector에 대한 강의입니다.")
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(responses=[DEFAULT_VALID_QUIZ_JSON])
        generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)

        assert len(provider.calls) == 1
        assert "RAG와 PGVector" in provider.calls[0]


class TestSummaryNotReady:
    def test_raises_when_no_summary_exists(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider()
        try:
            generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)
            raise AssertionError("SUMMARY_NOT_READY가 발생해야 합니다.")
        except AppError as exc:
            assert exc.code == "SUMMARY_NOT_READY"

        # 사용 오류이므로 quiz 상태를 건드리지 않는다.
        stored = db_session.execute(select(Quiz).where(Quiz.id == quiz.id)).scalar_one()
        assert stored.status == QuizStatus.GENERATING.value

    def test_raises_when_summary_has_empty_detailed_notes(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session, detailed_notes="")
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider()
        try:
            generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)
            raise AssertionError("SUMMARY_NOT_READY가 발생해야 합니다.")
        except AppError as exc:
            assert exc.code == "SUMMARY_NOT_READY"


class TestRetryPolicy:
    """§3.4: 429/5xx/타임아웃만 재시도, 4xx(형식 위반 포함)는 즉시 실패."""

    def test_quota_exceeded_retries_and_eventually_succeeds(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(
            responses=[
                AppError("LLM_QUOTA_EXCEEDED", retryable=True),
                DEFAULT_VALID_QUIZ_JSON,
            ]
        )
        result = generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)

        assert result.status == QuizStatus.DONE.value
        assert len(provider.calls) == 2

    def test_quota_exceeded_exhausts_retries_and_fails(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(responses=[AppError("LLM_QUOTA_EXCEEDED", retryable=True)])
        result = generate_quiz(db_session, session, quiz, provider, max_retries=3, sleep=_no_sleep)

        assert result.status == QuizStatus.FAILED.value
        assert result.error_code == "LLM_QUOTA_EXCEEDED"
        assert len(provider.calls) == 3

    def test_non_retryable_error_fails_immediately_without_retry(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(responses=[AppError("LLM_NOT_CONFIGURED", retryable=False)])
        result = generate_quiz(db_session, session, quiz, provider, max_retries=3, sleep=_no_sleep)

        assert result.status == QuizStatus.FAILED.value
        assert result.error_code == "LLM_NOT_CONFIGURED"
        assert len(provider.calls) == 1

    def test_format_violation_retries_once_then_succeeds(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(responses=["이것은 JSON이 아닙니다", DEFAULT_VALID_QUIZ_JSON])
        result = generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)

        assert result.status == QuizStatus.DONE.value
        assert len(provider.calls) == 2

    def test_format_violation_twice_fails_without_backoff_retry(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        provider = FakeLlmProvider(responses=["이것도 JSON이 아닙니다"])
        result = generate_quiz(db_session, session, quiz, provider, max_retries=3, sleep=_no_sleep)

        assert result.status == QuizStatus.FAILED.value
        assert result.error_code == "LLM_INVALID_RESPONSE"
        # 형식위반 1회 재요청(quiz_generator.py) = provider.generate 2회. 이건 "1번의 시도"로
        # 취급되므로 백오프 재시도 루프는 더 돌지 않는다 (max_retries와 무관).
        assert len(provider.calls) == 2


class TestEmptyQuestionsRejected:
    def test_empty_questions_list_treated_as_format_violation(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        quiz = _make_quiz(db_session, session)

        raw = make_quiz_json(questions=[])
        provider = FakeLlmProvider(responses=[raw, DEFAULT_VALID_QUIZ_JSON])
        result = generate_quiz(db_session, session, quiz, provider, sleep=_no_sleep)

        assert result.status == QuizStatus.DONE.value
        assert len(provider.calls) == 2
