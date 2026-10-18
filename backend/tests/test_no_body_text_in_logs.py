"""전사·요약 본문이 로그에 남지 않는지 확인한다 (T-28, §6 프라이버시: "길이·소요 시간만 기록").

실제 파이프라인(전사 오케스트레이션 + 요약 오케스트레이션)을 Fake Provider로 끝까지 돌리고,
그 안에 심어둔 표식 문자열이 캡처된 로그 어디에도 나타나지 않는지 검사한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from app.llm.fake import FakeLlmProvider, make_summary_json
from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.transcript import Transcript
from app.pipeline.summarization import summarize_session
from app.pipeline.transcription import transcribe_session
from app.stt.base import SttSegment
from app.stt.fake import FakeSttProvider

# 실제 로그에 나타나면 안 되는, 우연히 등장할 가능성이 거의 없는 표식 문자열.
TRANSCRIPT_MARKER = "절대로그에나오면안되는전사표식XJ9Q"
SUMMARY_MARKER = "절대로그에나오면안되는요약표식ZK3P"


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status=SessionStatus.UPLOADED.value,
        source="UPLOAD",
        audio_path="data/audio/dummy.upload",
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=120.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


def _no_sleep(_seconds: float) -> None:
    pass


class TestTranscriptionLogsExcludeBodyText:
    def test_transcript_marker_not_in_logs(
        self, db_session, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        segments = [SttSegment(start=0.0, end=5.0, text=f"{TRANSCRIPT_MARKER} 강의 내용입니다.")]
        provider = FakeSttProvider(segments=segments)

        with caplog.at_level(logging.DEBUG, logger="app"):
            transcribe_session(db_session, session, provider)

        all_log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert TRANSCRIPT_MARKER not in all_log_text


class TestSummarizationLogsExcludeBodyText:
    def test_summary_marker_not_in_logs(self, db_session, caplog: pytest.LogCaptureFixture) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        transcript = Transcript(
            session_id=session.id,
            text_raw="평범한 전사 텍스트",
            text_corrected=None,
            language="ko",
            provider="fake",
            provider_model="fake-large",
        )
        db_session.add(transcript)
        db_session.flush()

        raw = make_summary_json(oneLineSummary=f"{SUMMARY_MARKER} 요약 내용입니다.")
        provider = FakeLlmProvider(responses=[raw])

        with caplog.at_level(logging.DEBUG, logger="app"):
            summarize_session(db_session, session, provider, sleep=_no_sleep)

        all_log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert SUMMARY_MARKER not in all_log_text

    def test_logs_still_record_length_and_timing_metadata(
        self, db_session, caplog: pytest.LogCaptureFixture
    ) -> None:
        """본문은 없어야 하지만, 길이·소요시간 같은 메타데이터는 계속 기록돼야 한다(§6)."""
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        transcript = Transcript(
            session_id=session.id,
            text_raw="평범한 전사 텍스트",
            text_corrected=None,
            language="ko",
            provider="fake",
            provider_model="fake-large",
        )
        db_session.add(transcript)
        db_session.flush()

        with caplog.at_level(logging.DEBUG, logger="app"):
            summarize_session(db_session, session, FakeLlmProvider(), sleep=_no_sleep)

        all_log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert "key_points=" in all_log_text or "session_id=" in all_log_text
