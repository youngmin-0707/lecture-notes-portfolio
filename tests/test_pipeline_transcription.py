"""전사 오케스트레이션 테스트 (T-12, US-04, §2.4).

Fake `SttProvider`로 실제 모델 없이 상태 전이·저장 로직을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.enums import SessionStatus
from app.models.glossary import GlossaryTerm
from app.models.session import Session
from app.models.transcript import Transcript, TranscriptSegment
from app.pipeline import progress as progress_module
from app.pipeline.transcription import transcribe_session
from app.stt.base import SttSegment
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


class TestSuccessfulTranscription:
    def test_transitions_to_transcribed_and_saves_transcript(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        segments = [
            SttSegment(start=0.0, end=5.2, text="오늘은 이진 탐색 트리에 대해 알아보겠습니다."),
            SttSegment(start=5.2, end=11.8, text="먼저 삽입 연산부터 보겠습니다."),
        ]
        provider = FakeSttProvider(
            segments=segments, elapsed_seconds=1.23, provider_model="fake-large"
        )

        result = transcribe_session(db_session, session, provider)

        assert result.status == SessionStatus.TRANSCRIBED.value
        assert result.error_code is None
        assert result.error_message is None

        transcript = db_session.execute(
            select(Transcript).where(Transcript.session_id == session.id)
        ).scalar_one()
        assert transcript.text_raw == (
            "오늘은 이진 탐색 트리에 대해 알아보겠습니다. 먼저 삽입 연산부터 보겠습니다."
        )
        # T-23: 용어집이 비어 있으면(이 테스트에는 아무 용어도 없다) 보정본은 원본과 같다 —
        # 그래도 항상 채워진다(§3.3 "원본과 보정본을 둘 다 보존").
        assert transcript.text_corrected == transcript.text_raw
        assert transcript.language == "ko"
        assert transcript.provider == "fake"
        assert transcript.provider_model == "fake-large"
        assert transcript.elapsed_seconds == pytest.approx(1.23)

        stored_segments = (
            db_session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.seq)
            )
            .scalars()
            .all()
        )
        assert [s.seq for s in stored_segments] == [0, 1]
        assert stored_segments[0].start_seconds == pytest.approx(0.0)
        assert stored_segments[0].end_seconds == pytest.approx(5.2)
        assert stored_segments[1].start_seconds == pytest.approx(5.2)

    def test_segments_are_monotonic_and_non_overlapping(self, db_session) -> None:
        """US-04: 세그먼트 시작 시각이 단조 증가하고 서로 겹치지 않는다."""
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        segments = [
            SttSegment(start=0.0, end=2.0, text="a"),
            SttSegment(start=2.0, end=4.0, text="b"),
            SttSegment(start=4.0, end=6.0, text="c"),
        ]
        provider = FakeSttProvider(segments=segments)

        transcribe_session(db_session, session, provider)

        transcript = db_session.execute(
            select(Transcript).where(Transcript.session_id == session.id)
        ).scalar_one()
        stored = (
            db_session.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.seq)
            )
            .scalars()
            .all()
        )
        starts = [s.start_seconds for s in stored]
        assert starts == sorted(starts)
        for prev, nxt in zip(stored, stored[1:], strict=False):
            assert prev.end_seconds <= nxt.start_seconds

    def test_progress_cleared_after_success(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        provider = FakeSttProvider(progress_updates=[(0.0, 5.0), (5.0, 5.0)])
        transcribe_session(db_session, session, provider)

        assert progress_module.get_progress(session.id) is None


class TestFailedTranscription:
    def test_app_error_sets_failed_status_with_code(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        provider = FakeSttProvider(error=AppError("STT_MODEL_UNAVAILABLE"))

        result = transcribe_session(db_session, session, provider)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "STT_MODEL_UNAVAILABLE"
        assert result.error_message

        assert (
            db_session.execute(
                select(Transcript).where(Transcript.session_id == session.id)
            ).first()
            is None
        )

    def test_unexpected_exception_maps_to_stt_failed(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        provider = FakeSttProvider(error=TimeoutError("stt timed out"))

        result = transcribe_session(db_session, session, provider)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "STT_FAILED"

    def test_progress_cleared_after_failure(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        provider = FakeSttProvider(error=RuntimeError("boom"), progress_updates=[(0.0, 5.0)])
        transcribe_session(db_session, session, provider)

        assert progress_module.get_progress(session.id) is None

    def test_no_transcript_saved_on_overlapping_segments(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        bad_segments = [
            SttSegment(start=0.0, end=5.0, text="a"),
            SttSegment(start=3.0, end=6.0, text="b (overlaps)"),
        ]
        provider = FakeSttProvider(segments=bad_segments)

        result = transcribe_session(db_session, session, provider)

        assert result.status == SessionStatus.FAILED.value
        assert result.error_code == "STT_FAILED"
        assert (
            db_session.execute(
                select(Transcript).where(Transcript.session_id == session.id)
            ).first()
            is None
        )


class TestGlossaryCorrection:
    """T-23, US-13: 프롬프트 바이어싱 + 전사 후 용어 보정."""

    def test_initial_prompt_built_from_applicable_glossary_terms(self, db_session) -> None:
        session = _make_session(course="자료구조")
        db_session.add(session)
        db_session.add_all(
            [
                GlossaryTerm(term="PostgreSQL", aliases=["포스트그레"], course=None),
                GlossaryTerm(term="이진 탐색 트리", aliases=["비에스티"], course="자료구조"),
                GlossaryTerm(term="다른과목전용", aliases=[], course="네트워크"),
            ]
        )
        db_session.flush()

        provider = FakeSttProvider()
        transcribe_session(db_session, session, provider)

        assert len(provider.calls) == 1
        prompt = provider.calls[0].initial_prompt
        assert prompt is not None
        assert "PostgreSQL" in prompt
        assert "이진 탐색 트리" in prompt
        assert "다른과목전용" not in prompt

    def test_explicit_initial_prompt_overrides_auto_generated(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.add(GlossaryTerm(term="PostgreSQL", aliases=["포스트그레"], course=None))
        db_session.flush()

        provider = FakeSttProvider()
        transcribe_session(db_session, session, provider, initial_prompt="커스텀 프롬프트")

        assert provider.calls[0].initial_prompt == "커스텀 프롬프트"

    def test_corrected_text_replaces_aliases_with_canonical_term(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.add(
            GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘", "포스트그레"], course=None)
        )
        db_session.flush()

        segments = [SttSegment(start=0.0, end=3.0, text="포스트그레스큐엘에서 조인을 하면")]
        provider = FakeSttProvider(segments=segments)

        transcribe_session(db_session, session, provider)

        transcript = db_session.execute(
            select(Transcript).where(Transcript.session_id == session.id)
        ).scalar_one()
        assert transcript.text_raw == "포스트그레스큐엘에서 조인을 하면"
        assert transcript.text_corrected == "PostgreSQL에서 조인을 하면"

    def test_longer_alias_matched_before_shorter_prefix_alias(self, db_session) -> None:
        """ "포스트그레"가 "포스트그레스큐엘"의 부분 치환을 깨뜨리면 안 된다 (§3.3)."""
        session = _make_session()
        db_session.add(session)
        db_session.add(
            GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘", "포스트그레"], course=None)
        )
        db_session.flush()

        segments = [SttSegment(start=0.0, end=1.0, text="포스트그레스큐엘 그리고 포스트그레")]
        provider = FakeSttProvider(segments=segments)

        transcribe_session(db_session, session, provider)

        transcript = db_session.execute(
            select(Transcript).where(Transcript.session_id == session.id)
        ).scalar_one()
        assert transcript.text_corrected == "PostgreSQL 그리고 PostgreSQL"

    def test_java_alias_does_not_break_javascript(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.add_all(
            [
                GlossaryTerm(term="Java", aliases=["자바"], course=None),
                GlossaryTerm(term="JavaScript", aliases=["자바스크립트"], course=None),
            ]
        )
        db_session.flush()

        segments = [SttSegment(start=0.0, end=1.0, text="자바스크립트와 자바는 다릅니다")]
        provider = FakeSttProvider(segments=segments)

        transcribe_session(db_session, session, provider)

        transcript = db_session.execute(
            select(Transcript).where(Transcript.session_id == session.id)
        ).scalar_one()
        assert transcript.text_corrected == "JavaScript와 Java는 다릅니다"


class TestProgressDuringTranscription:
    def test_progress_callback_updates_store_mid_processing(self, db_session) -> None:
        """provider가 진행률 콜백을 호출하는 시점에 스토어에 반영되는지 확인한다."""
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        observed_percentages: list[float] = []

        class ObservingProvider(FakeSttProvider):
            def transcribe(
                self, audio_path, *, language, initial_prompt=None, progress_callback=None
            ):
                result = super().transcribe(
                    audio_path,
                    language=language,
                    initial_prompt=initial_prompt,
                    progress_callback=progress_callback,
                )
                snapshot = progress_module.get_progress(session.id)
                if snapshot is not None:
                    observed_percentages.append(snapshot.percent)
                return result

        provider = ObservingProvider(progress_updates=[(2.5, 10.0), (10.0, 10.0)])
        transcribe_session(db_session, session, provider)

        assert observed_percentages == [100.0]  # 마지막 콜백(10.0/10.0=100%) 반영 확인
