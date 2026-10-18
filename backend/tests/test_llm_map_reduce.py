"""map-reduce 긴 전사 요약 테스트 (T-21, §3.4, US-12)."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.llm.chunking import TimedSegment, chunk_segments
from app.llm.fake import FakeLlmProvider, make_summary_json
from app.llm.map_reduce import summarize_transcript


def _long_segments(count: int = 20, sentence_chars: int = 50) -> list[TimedSegment]:
    return [
        TimedSegment(start_seconds=i * 5.0, text=f"문장{i}: " + ("가" * sentence_chars))
        for i in range(count)
    ]


class TestSingleChunkPath:
    def test_fits_in_one_chunk_calls_provider_once(self) -> None:
        segments = [TimedSegment(start_seconds=0.0, text="짧은 강의 내용")]
        provider = FakeLlmProvider()
        sleep_calls: list[float] = []

        result = summarize_transcript(
            provider,
            segments,
            title="제목",
            chunk_size_tokens=4000,
            overlap_tokens=200,
            call_interval_seconds=1.0,
            sleep=sleep_calls.append,
        )

        assert result.one_line_summary
        assert len(provider.calls) == 1
        assert sleep_calls == []

    def test_single_chunk_prompt_contains_timecoded_text(self) -> None:
        segments = [TimedSegment(start_seconds=65.0, text="발화 내용")]
        provider = FakeLlmProvider()

        summarize_transcript(
            provider,
            segments,
            title="제목",
            chunk_size_tokens=4000,
            overlap_tokens=200,
            call_interval_seconds=1.0,
            sleep=lambda _: None,
        )

        assert "[01:05] 발화 내용" in provider.calls[0]

    def test_empty_segments_still_produces_a_call(self) -> None:
        provider = FakeLlmProvider()

        result = summarize_transcript(
            provider,
            [],
            title="제목",
            chunk_size_tokens=4000,
            overlap_tokens=200,
            call_interval_seconds=1.0,
            sleep=lambda _: None,
        )

        assert result.one_line_summary
        assert len(provider.calls) == 1


class TestMapReducePath:
    def test_triggers_map_reduce_and_calls_map_plus_reduce(self) -> None:
        segments = _long_segments()
        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)
        assert len(chunks) >= 3, "테스트 전제: 여러 청크로 쪼개져야 map-reduce 경로를 검증한다"

        responses = [
            make_summary_json(oneLineSummary=f"구간{i + 1} 요약본") for i in range(len(chunks))
        ]
        responses.append(make_summary_json(oneLineSummary="최종 통합 요약"))
        provider = FakeLlmProvider(responses=responses)
        sleep_calls: list[float] = []

        result = summarize_transcript(
            provider,
            segments,
            title="제목",
            chunk_size_tokens=100,
            overlap_tokens=20,
            call_interval_seconds=2.5,
            sleep=sleep_calls.append,
        )

        assert result.one_line_summary == "최종 통합 요약"
        # map 호출 N번 + reduce 호출 1번.
        assert len(provider.calls) == len(chunks) + 1

    def test_sequential_calls_with_interval_between_map_steps(self) -> None:
        segments = _long_segments()
        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)

        responses = [make_summary_json() for _ in range(len(chunks) + 1)]
        provider = FakeLlmProvider(responses=responses)
        sleep_calls: list[float] = []

        summarize_transcript(
            provider,
            segments,
            title="제목",
            chunk_size_tokens=100,
            overlap_tokens=20,
            call_interval_seconds=2.5,
            sleep=sleep_calls.append,
        )

        # map 청크 사이에만 간격을 둔다 (청크 N개 → 간격 N-1번). reduce 호출 전에는 넣지 않는다.
        assert sleep_calls == [2.5] * (len(chunks) - 1)

    def test_final_summary_reflects_both_first_and_last_chunk(self) -> None:
        """US-12: 최종 요약에 강의 전반부와 후반부 내용이 모두 반영돼야 한다."""
        segments = _long_segments()
        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)

        responses = [
            make_summary_json(oneLineSummary=f"구간{i + 1} 요약본") for i in range(len(chunks))
        ]
        responses.append(make_summary_json(oneLineSummary="최종 통합 요약"))
        provider = FakeLlmProvider(responses=responses)

        summarize_transcript(
            provider,
            segments,
            title="제목",
            chunk_size_tokens=100,
            overlap_tokens=20,
            call_interval_seconds=0.0,
            sleep=lambda _: None,
        )

        final_prompt = provider.calls[-1]
        assert "구간1 요약본" in final_prompt
        assert f"구간{len(chunks)} 요약본" in final_prompt

    def test_map_step_retryable_error_propagates_to_caller(self) -> None:
        """map 단계 실패는 통째로 상위(재시도 루프)로 전파된다 — 여기서 삼키지 않는다."""
        segments = _long_segments()
        provider = FakeLlmProvider(responses=[AppError("LLM_QUOTA_EXCEEDED", retryable=True)])

        with pytest.raises(AppError) as exc_info:
            summarize_transcript(
                provider,
                segments,
                title="제목",
                chunk_size_tokens=100,
                overlap_tokens=20,
                call_interval_seconds=0.0,
                sleep=lambda _: None,
            )

        assert exc_info.value.code == "LLM_QUOTA_EXCEEDED"
        assert exc_info.value.retryable is True
