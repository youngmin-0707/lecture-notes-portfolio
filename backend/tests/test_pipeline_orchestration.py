"""전사→요약 파이프라인 오케스트레이션 테스트 (T-19, US-02, §2.4).

Fake STT/LLM Provider로 `run_pipeline()`의 상태 전이·연결 로직을 검증한다. HTTP/BackgroundTasks
계층은 `tests/test_sessions_process_api.py`에서 별도로 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.llm.fake import FakeLlmProvider
from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.pipeline.orchestration import run_pipeline
from app.stt.fake import FakeSttProvider


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
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


class TestRunPipelineFullSuccess:
    def test_transcribe_then_summarize_reaches_done(self, db_session, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_stt_provider",
            lambda model=None: FakeSttProvider(),
        )
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_llm_provider",
            lambda name=None: FakeLlmProvider(),
        )

        session = _make_session()
        db_session.add(session)
        db_session.flush()

        result = run_pipeline(db_session, session)

        assert result.status == SessionStatus.DONE.value
        assert (
            db_session.execute(
                select(Transcript).where(Transcript.session_id == session.id)
            ).scalar_one_or_none()
            is not None
        )
        assert (
            db_session.execute(
                select(Summary).where(Summary.session_id == session.id)
            ).scalar_one_or_none()
            is not None
        )


class TestRunPipelineSkipSummary:
    def test_skip_summary_stops_after_transcribed(self, db_session, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_stt_provider",
            lambda model=None: FakeSttProvider(),
        )
        llm_calls: list[str] = []
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_llm_provider",
            lambda name=None: llm_calls.append("called") or FakeLlmProvider(),
        )

        session = _make_session()
        db_session.add(session)
        db_session.flush()

        result = run_pipeline(db_session, session, skip_summary=True)

        assert result.status == SessionStatus.TRANSCRIBED.value
        assert llm_calls == []  # LLM provider가 아예 조립되지 않았다.


class TestRunPipelineSttFailureStopsBeforeSummary:
    def test_stt_failure_does_not_call_llm(self, db_session, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_stt_provider",
            lambda model=None: FakeSttProvider(error=AppError("STT_FAILED")),
        )
        llm_calls: list[str] = []
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_llm_provider",
            lambda name=None: llm_calls.append("called") or FakeLlmProvider(),
        )

        session = _make_session()
        db_session.add(session)
        db_session.flush()

        result = run_pipeline(db_session, session)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "STT_FAILED"
        assert llm_calls == []


class TestRunPipelineReusesExistingTranscript:
    """§2.4: 전사가 이미 있으면 요약만 다시 실행한다 (재실행/복구 스윕 이후 재시도 공통)."""

    def test_existing_transcript_skips_stt_and_goes_straight_to_summary(
        self, db_session, monkeypatch
    ) -> None:
        stt_calls: list[str] = []
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_stt_provider",
            lambda model=None: stt_calls.append("called") or FakeSttProvider(),
        )
        monkeypatch.setattr(
            "app.pipeline.orchestration.build_llm_provider",
            lambda name=None: FakeLlmProvider(),
        )

        session = _make_session(status=SessionStatus.FAILED.value, error_code="INTERRUPTED")
        db_session.add(session)
        db_session.flush()
        transcript = Transcript(
            session_id=session.id,
            text_raw="이미 저장된 전사 원문입니다.",
            language="ko",
            provider="fake",
            provider_model="fake-large",
        )
        db_session.add(transcript)
        db_session.flush()

        result = run_pipeline(db_session, session)

        assert result.status == SessionStatus.DONE.value
        assert stt_calls == []  # STT provider가 조립되지 않았다 — 전사를 재실행하지 않는다.
        # 기존 전사가 그대로 재사용되었다 (새로 생성된 두 번째 transcript가 없다).
        transcripts = (
            db_session.execute(select(Transcript).where(Transcript.session_id == session.id))
            .scalars()
            .all()
        )
        assert len(transcripts) == 1
        assert transcripts[0].id == transcript.id
