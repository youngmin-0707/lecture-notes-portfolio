"""요약 오케스트레이션 테스트 (T-18, US-05, US-08, §2.4, §3.4).

Fake `LlmProvider`로 실제 Ollama 없이 상태 전이·저장·재시도 로직을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.llm.fake import DEFAULT_VALID_SUMMARY_JSON, FakeLlmProvider, make_summary_json
from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.pipeline import progress as progress_module
from app.pipeline.summarization import summarize_session


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status=SessionStatus.TRANSCRIBED.value,
        source="UPLOAD",
        audio_path="data/audio/dummy.upload",
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=3600.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


def _add_transcript(db_session, session: Session, *, text: str | None = None) -> Transcript:
    transcript = Transcript(
        session_id=session.id,
        text_raw=text or "오늘은 이진 탐색 트리에 대해 알아보겠습니다.",
        text_corrected=None,
        language="ko",
        provider="fake",
        provider_model="fake-large",
        elapsed_seconds=1.5,
    )
    db_session.add(transcript)
    db_session.flush()
    return transcript


def _no_sleep(_seconds: float) -> None:
    """백오프 재시도 테스트가 실제로 기다리지 않도록 주입하는 sleep 대체 함수."""


class TestSuccessfulSummarization:
    def test_transitions_to_done_and_saves_summary(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(provider_model="fake-qwen3")
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert result.error_code is None
        assert result.error_message is None

        summary = db_session.execute(
            select(Summary).where(Summary.session_id == session.id)
        ).scalar_one()
        assert summary.provider == "fake"
        assert summary.provider_model == "fake-qwen3"
        assert "## 한 줄 요약" in summary.content_markdown
        assert "## 과제 및 공지" in summary.content_markdown
        assert summary.action_items == []
        assert len(summary.key_points) >= 3
        assert summary.key_points[0]["atSeconds"] is not None

    def test_progress_cleared_after_success(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider()
        summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert progress_module.get_progress(session.id) is None

    def test_action_items_preserved_when_present(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        raw = make_summary_json(actionItems=[{"text": "과제 3번 제출", "dueDate": "2026-08-27"}])
        provider = FakeLlmProvider(responses=[raw])
        summarize_session(db_session, session, provider, sleep=_no_sleep)

        summary = db_session.execute(
            select(Summary).where(Summary.session_id == session.id)
        ).scalar_one()
        assert summary.action_items == [{"text": "과제 3번 제출", "dueDate": "2026-08-27"}]
        assert "과제 3번 제출" in summary.content_markdown


class TestTranscriptPreservedOnFailure:
    """US-08: 요약이 실패해도 전사(transcripts/transcript_segments)는 절대 삭제되지 않는다."""

    def test_permanent_llm_failure_preserves_transcript(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        transcript = _add_transcript(db_session, session)

        provider = FakeLlmProvider(responses=[AppError("LLM_FAILED", retryable=False)])
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "LLM_FAILED"

        preserved = db_session.get(Transcript, transcript.id)
        assert preserved is not None
        assert preserved.text_raw == transcript.text_raw

    def test_no_summary_saved_on_failure(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(responses=["끝까지 JSON이 아닙니다"])
        result = summarize_session(db_session, session, provider, max_retries=1, sleep=_no_sleep)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "LLM_INVALID_RESPONSE"
        assert (
            db_session.execute(select(Summary).where(Summary.session_id == session.id)).first()
            is None
        )


class TestRetryPolicy:
    """§3.4: 429/5xx/타임아웃만 재시도, 4xx(형식 위반 포함)는 즉시 실패."""

    def test_quota_exceeded_retries_and_eventually_succeeds(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(
            responses=[
                AppError("LLM_QUOTA_EXCEEDED", retryable=True),
                DEFAULT_VALID_SUMMARY_JSON,
            ]
        )
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        # 첫 시도(429) + 재시도(성공) = provider.generate 2회 호출.
        assert len(provider.calls) == 2

    def test_quota_exceeded_exhausts_retries_and_fails(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(responses=[AppError("LLM_QUOTA_EXCEEDED", retryable=True)])
        result = summarize_session(db_session, session, provider, max_retries=3, sleep=_no_sleep)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "LLM_QUOTA_EXCEEDED"
        assert len(provider.calls) == 3

    def test_non_retryable_error_fails_immediately_without_retry(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(responses=[AppError("LLM_NOT_CONFIGURED", retryable=False)])
        result = summarize_session(db_session, session, provider, max_retries=3, sleep=_no_sleep)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "LLM_NOT_CONFIGURED"
        # 재시도 불가 오류이므로 max_retries와 무관하게 1회만 호출된다.
        assert len(provider.calls) == 1

    def test_backoff_sleep_called_with_increasing_delays(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(
            responses=[
                AppError("LLM_FAILED", retryable=True),
                AppError("LLM_FAILED", retryable=True),
                DEFAULT_VALID_SUMMARY_JSON,
            ]
        )
        sleep_calls: list[float] = []
        summarize_session(
            db_session,
            session,
            provider,
            max_retries=3,
            backoff_base_seconds=1.0,
            sleep=sleep_calls.append,
        )

        assert sleep_calls == [1.0, 2.0]  # 지수 백오프: 1 * 2^0, 1 * 2^1


class TestTranscriptNotReady:
    def test_raises_when_transcript_missing(self, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBING.value)
        db_session.add(session)
        db_session.flush()

        provider = FakeLlmProvider()
        with pytest.raises(AppError) as exc_info:
            summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert exc_info.value.code == "TRANSCRIPT_NOT_READY"
        # 상태를 건드리지 않았어야 한다 (호출부 사용 오류이므로).
        assert session.status == SessionStatus.TRANSCRIBING.value
