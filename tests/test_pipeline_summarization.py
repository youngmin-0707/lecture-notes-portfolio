"""요약 오케스트레이션 테스트 (T-18, US-05, US-08, §2.4, §3.4).

Fake `LlmProvider`로 실제 Ollama 없이 상태 전이·저장·재시도 로직을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.llm.chunking import TimedSegment, chunk_segments
from app.llm.fake import DEFAULT_VALID_SUMMARY_JSON, FakeLlmProvider, make_summary_json
from app.models.enums import SessionStatus
from app.models.glossary import GlossaryTerm
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript, TranscriptSegment
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
        assert summary.detailed_notes_markdown
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

    def test_detailed_notes_persisted(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        notes = "1. 과제 3번 제출 안내\n마감은 다음 주 금요일입니다."
        raw = make_summary_json(detailedNotes=notes)
        provider = FakeLlmProvider(responses=[raw])
        summarize_session(db_session, session, provider, sleep=_no_sleep)

        summary = db_session.execute(
            select(Summary).where(Summary.session_id == session.id)
        ).scalar_one()
        assert summary.detailed_notes_markdown == notes
        assert "과제 3번 제출" in summary.content_markdown


class TestSuggestedTitleAppliedOnSuccess:
    """2026-08-30: 제목을 직접 정한 적이 없으면 요약 완료 시 LLM 제안 제목으로 갱신한다.

    하루에 여러 건을 올리면 기본 제목("YYYY-MM-DD 수업")이 전부 똑같아 구별이 안 되는 걸
    실사용 중 실제로 겪은 뒤 도입했다.
    """

    def test_title_updated_when_not_customized(self, db_session) -> None:
        session = _make_session(title="2026-08-30 수업", title_customized=False)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        raw = make_summary_json(suggestedTitle="이진 탐색 트리 삽입/탐색 구현")
        provider = FakeLlmProvider(responses=[raw])
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert result.title == "이진 탐색 트리 삽입/탐색 구현"

    def test_title_not_overwritten_when_customized(self, db_session) -> None:
        session = _make_session(title="내가 직접 정한 제목", title_customized=True)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        raw = make_summary_json(suggestedTitle="LLM이 제안한 다른 제목")
        provider = FakeLlmProvider(responses=[raw])
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert result.title == "내가 직접 정한 제목"

    def test_title_truncated_to_column_max_length(self, db_session) -> None:
        session = _make_session(title_customized=False)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        long_title = "가" * 250
        raw = make_summary_json(suggestedTitle=long_title)
        provider = FakeLlmProvider(responses=[raw])
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert len(result.title) == 200


class TestChunkSizeIsProviderAware:
    """2026-08-30: OpenAI는 컨텍스트가 넓어(1.05M 토큰) map-reduce가 사실상 필요 없다 —
    Ollama와 같은 좁은 청크 크기를 그대로 쓰면 불필요하게 여러 번 호출돼 시간·비용이
    2~3배 든다는 걸 실사용 중 겪은 뒤 provider별로 분리했다.
    """

    def _add_long_transcript(self, db_session, session: Session, *, segment_count: int) -> None:
        """세그먼트 여러 개로 나눠 총 길이가 Ollama 기본 청크 크기(4000 "토큰" ≈ 8800자)는
        넘지만 OpenAI 기본 청크 크기(200000)에는 한참 못 미치게 만든다. `chunk_segments()`는
        세그먼트 하나를 중간에 쪼개지 않으므로, 여러 개로 나눠 넣어야 청크 분할이 실제로
        일어날 수 있다.
        """
        transcript = Transcript(
            session_id=session.id,
            text_raw="(세그먼트 참고)",
            text_corrected=None,
            language="ko",
            provider="fake",
            provider_model="fake-large",
            elapsed_seconds=1.5,
        )
        db_session.add(transcript)
        db_session.flush()
        segment_text = "이 강의에서는 벡터 검색과 임베딩에 대해 자세히 설명합니다. " * 10  # ~500자
        for i in range(segment_count):
            db_session.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    seq=i,
                    start_seconds=float(i * 10),
                    end_seconds=float(i * 10 + 9),
                    text=segment_text,
                )
            )
        db_session.flush()

    def test_ollama_provider_triggers_map_reduce_for_long_transcript(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        self._add_long_transcript(db_session, session, segment_count=50)

        provider = FakeLlmProvider(provider_name="ollama")
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        # map(2개 이상) + reduce(1개) = 최소 3번 호출.
        assert len(provider.calls) >= 3

    def test_openai_provider_uses_single_call_for_same_transcript(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        self._add_long_transcript(db_session, session, segment_count=50)

        provider = FakeLlmProvider(provider_name="openai")
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert len(provider.calls) == 1


class TestAudioDeletedAfterSuccess:
    """2026-08-29: 요약까지 성공(DONE)하면 원본 오디오는 지운다 — 실사용 확인 후 도입."""

    def test_audio_file_deleted_and_path_cleared_on_success(
        self, db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        audio_file = tmp_path / "lecture.wav"
        audio_file.write_bytes(b"RIFF....")
        session = _make_session(audio_path=str(audio_file))
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider()
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert not audio_file.exists()
        assert result.audio_path is None

    def test_audio_kept_when_summarization_fails(self, db_session, tmp_path) -> None:
        audio_file = tmp_path / "lecture.wav"
        audio_file.write_bytes(b"RIFF....")
        session = _make_session(audio_path=str(audio_file))
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider(responses=[AppError("LLM_INVALID_RESPONSE", retryable=False)])
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.FAILED.value
        assert audio_file.exists()
        assert result.audio_path == str(audio_file)

    def test_disabled_via_setting_keeps_audio(
        self, db_session, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "DELETE_AUDIO_AFTER_PROCESSING", False)
        audio_file = tmp_path / "lecture.wav"
        audio_file.write_bytes(b"RIFF....")
        session = _make_session(audio_path=str(audio_file))
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider()
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert audio_file.exists()
        assert result.audio_path == str(audio_file)

    def test_resummarize_after_audio_already_deleted_does_not_error(
        self, db_session, tmp_path
    ) -> None:
        """재요약 시점엔 첫 성공 때 이미 오디오가 지워져 있을 수 있다 — 조용히 넘어가야 한다."""
        session = _make_session(audio_path=None)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        provider = FakeLlmProvider()
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert result.audio_path is None


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


class TestMapReduceIntegration:
    """T-21, US-12: 파이프라인 레벨에서 map-reduce가 실제로 트리거되는지 확인한다."""

    def _add_many_segments(self, db_session, transcript: Transcript, count: int = 20) -> None:
        db_session.add_all(
            [
                TranscriptSegment(
                    transcript_id=transcript.id,
                    seq=i,
                    start_seconds=i * 5.0,
                    end_seconds=i * 5.0 + 4.0,
                    text=f"문장{i}: " + ("가" * 50),
                )
                for i in range(count)
            ]
        )
        db_session.flush()

    def test_long_transcript_with_small_chunk_size_triggers_map_reduce(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        transcript = _add_transcript(db_session, session)
        self._add_many_segments(db_session, transcript)

        segments = [
            TimedSegment(start_seconds=s.start_seconds, text=s.text) for s in transcript.segments
        ]
        chunk_count = len(chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20))
        assert chunk_count >= 3, "테스트 전제: 여러 청크로 쪼개져야 한다"

        responses = [make_summary_json() for _ in range(chunk_count + 1)]
        provider = FakeLlmProvider(responses=responses)

        result = summarize_session(
            db_session,
            session,
            provider,
            sleep=_no_sleep,
            chunk_size_tokens=100,
            chunk_overlap_tokens=20,
            map_call_interval_seconds=0.0,
        )

        assert result.status == SessionStatus.DONE.value
        assert len(provider.calls) == chunk_count + 1
        summary = db_session.execute(
            select(Summary).where(Summary.session_id == session.id)
        ).scalar_one()
        assert summary.provider_model == "fake-llm-model"

    def test_short_transcript_with_default_chunk_size_stays_single_shot(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        transcript = _add_transcript(db_session, session)
        self._add_many_segments(db_session, transcript, count=3)

        provider = FakeLlmProvider()
        result = summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert result.status == SessionStatus.DONE.value
        assert len(provider.calls) == 1

    def test_segment_text_corrected_with_glossary_before_summarizing(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.add(GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘"], course=None))
        db_session.flush()
        transcript = _add_transcript(db_session, session)
        db_session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                seq=0,
                start_seconds=0.0,
                end_seconds=3.0,
                text="포스트그레스큐엘에서 조인을 하면",
            )
        )
        db_session.flush()

        provider = FakeLlmProvider()
        summarize_session(db_session, session, provider, sleep=_no_sleep)

        assert "PostgreSQL에서 조인을 하면" in provider.calls[0]
        assert "포스트그레스큐엘" not in provider.calls[0]


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


class TestTextSessionHasNoTimestamps:
    """2026-09-14: 텍스트 파일로 만든 세션은 시간축이 없으므로 타임스탬프를 붙이지 않는다."""

    def test_key_point_timestamps_dropped_for_text_source(self, db_session) -> None:
        session = _make_session(
            source="TEXT",
            audio_path=None,
            duration_seconds=None,
            original_filename="note.txt",
            mime_type="text/plain",
        )
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        summarize_session(db_session, session, FakeLlmProvider(), sleep=_no_sleep)

        summary = db_session.execute(
            select(Summary).where(Summary.session_id == session.id)
        ).scalar_one()
        assert summary.key_points  # 항목 자체는 그대로 남는다.
        assert all(point["atSeconds"] is None for point in summary.key_points)
        # LLM이 지어낸 "[MM:SS]"가 마크다운에도 남으면 안 된다.
        assert "## 핵심 주제" in summary.content_markdown
        assert "[00:" not in summary.content_markdown

    def test_audio_session_keeps_timestamps(self, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        summarize_session(db_session, session, FakeLlmProvider(), sleep=_no_sleep)

        summary = db_session.execute(
            select(Summary).where(Summary.session_id == session.id)
        ).scalar_one()
        assert any(point["atSeconds"] is not None for point in summary.key_points)
