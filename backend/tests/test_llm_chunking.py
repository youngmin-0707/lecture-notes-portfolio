"""전사 청크 분할 유닛 테스트 (T-21, §3.4, US-12)."""

from __future__ import annotations

from app.llm.chunking import CHARS_PER_TOKEN_ESTIMATE, TimedSegment, chunk_segments, estimate_tokens


def _segments(*texts: str, gap_seconds: float = 5.0) -> list[TimedSegment]:
    return [TimedSegment(start_seconds=i * gap_seconds, text=t) for i, t in enumerate(texts)]


class TestEstimateTokens:
    def test_empty_text_is_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_text_is_at_least_one(self) -> None:
        assert estimate_tokens("a") >= 1

    def test_scales_roughly_with_length(self) -> None:
        short = estimate_tokens("가" * 10)
        long = estimate_tokens("가" * 100)
        assert long > short


class TestChunkSegmentsNoSplitNeeded:
    def test_empty_segments_returns_empty_list(self) -> None:
        assert chunk_segments([], chunk_size_tokens=4000, overlap_tokens=200) == []

    def test_small_transcript_fits_in_single_chunk(self) -> None:
        segments = _segments("짧은 문장 1", "짧은 문장 2", "짧은 문장 3")

        chunks = chunk_segments(segments, chunk_size_tokens=4000, overlap_tokens=200)

        assert len(chunks) == 1
        assert chunks[0] == segments


class TestChunkSegmentsSplitting:
    def _long_segments(self, count: int, sentence_chars: int = 50) -> list[TimedSegment]:
        return _segments(*[f"문장{i}: " + ("가" * sentence_chars) for i in range(count)])

    def test_splits_into_multiple_chunks_when_over_budget(self) -> None:
        # 세그먼트 하나가 대략 50자 ≈ 23토큰. 청크 크기를 100토큰으로 좁게 잡아 강제로 쪼갠다.
        segments = self._long_segments(20)

        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)

        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) > 0

    def test_first_and_last_original_segment_covered(self) -> None:
        """US-12: 강의 전반부와 후반부 내용이 모두 어딘가의 청크에 남아있어야 한다."""
        segments = self._long_segments(20)

        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)

        all_texts_in_chunks = {s.text for chunk in chunks for s in chunk}
        assert segments[0].text in all_texts_in_chunks
        assert segments[-1].text in all_texts_in_chunks
        # 첫 청크가 강의 도입부를, 마지막 청크가 마무리부를 담고 있어야 한다.
        assert segments[0] in chunks[0]
        assert segments[-1] in chunks[-1]

    def test_consecutive_chunks_overlap(self) -> None:
        segments = self._long_segments(20)

        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)

        for prev_chunk, next_chunk in zip(chunks, chunks[1:], strict=False):
            overlap = set(prev_chunk) & set(next_chunk)
            assert overlap, "인접한 청크 사이에 겹치는 세그먼트가 있어야 한다 (§3.4 오버랩)"

    def test_no_segment_is_split_mid_text(self) -> None:
        """청크는 세그먼트 단위로만 나뉜다 — 세그먼트 텍스트 자체는 절대 잘리지 않는다."""
        segments = self._long_segments(20)

        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=20)

        original_texts = {s.text for s in segments}
        for chunk in chunks:
            for seg in chunk:
                assert seg.text in original_texts

    def test_zero_overlap_still_splits_without_error(self) -> None:
        segments = self._long_segments(20)

        chunks = chunk_segments(segments, chunk_size_tokens=100, overlap_tokens=0)

        assert len(chunks) > 1
        all_texts_in_chunks = {s.text for chunk in chunks for s in chunk}
        assert all_texts_in_chunks == {s.text for s in segments}

    def test_single_oversized_segment_becomes_its_own_chunk(self) -> None:
        huge = TimedSegment(start_seconds=0.0, text="가" * 5000)
        small = TimedSegment(start_seconds=100.0, text="짧은 문장")

        chunks = chunk_segments([huge, small], chunk_size_tokens=100, overlap_tokens=20)

        assert huge in chunks[0]
        assert any(small in chunk for chunk in chunks)


class TestChunkSizeCharsApproximation:
    def test_chars_per_token_estimate_is_positive(self) -> None:
        assert CHARS_PER_TOKEN_ESTIMATE > 0
