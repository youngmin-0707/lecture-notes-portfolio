"""요약 프롬프트 구성 테스트 (T-16/T-21, §3.4)."""

from __future__ import annotations

from app.llm.chunking import TimedSegment
from app.llm.prompt import build_summary_prompt, format_timecoded_text


class TestFormatTimecodedText:
    def test_formats_mm_ss_prefix_per_segment(self) -> None:
        segments = [
            TimedSegment(start_seconds=0.0, text="오늘은 이진 탐색 트리를 배웁니다."),
            TimedSegment(start_seconds=65.0, text="먼저 삽입 연산부터 보겠습니다."),
        ]

        text = format_timecoded_text(segments)

        assert text == (
            "[00:00] 오늘은 이진 탐색 트리를 배웁니다.\n[01:05] 먼저 삽입 연산부터 보겠습니다."
        )

    def test_minutes_beyond_two_digits_not_truncated(self) -> None:
        # 125분 7초 = 7507초 (240분 강의 상한 안에서도 발생 가능).
        segments = [TimedSegment(start_seconds=7507.0, text="후반부 발화")]

        text = format_timecoded_text(segments)

        assert text == "[125:07] 후반부 발화"

    def test_empty_segments_returns_empty_string(self) -> None:
        assert format_timecoded_text([]) == ""

    def test_negative_start_clamped_to_zero(self) -> None:
        segments = [TimedSegment(start_seconds=-1.0, text="경계값")]

        assert format_timecoded_text(segments) == "[00:00] 경계값"


class TestBuildSummaryPromptTimecodeInstructions:
    def test_instructs_llm_to_read_atseconds_from_timecodes(self) -> None:
        prompt = build_summary_prompt("[00:00] 발화", title="제목")

        assert "MM:SS" in prompt
        assert "atSeconds" in prompt
        assert "임의로 추정하지" in prompt

    def test_includes_transcript_text_verbatim(self) -> None:
        text = "[00:00] 오늘은 이진 탐색 트리에 대해 알아보겠습니다."
        prompt = build_summary_prompt(text, title="자료구조 7주차", course="자료구조")

        assert text in prompt
        assert "자료구조 7주차" in prompt
        assert "자료구조" in prompt
