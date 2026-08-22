"""내보내기 렌더러 유닛 테스트 (T-27, §5.3⑦, US-16)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.export.renderers import render_markdown_export, render_srt_export, render_txt_export
from app.models.summary import Summary
from app.models.transcript import Transcript, TranscriptSegment


def _make_transcript(*, corrected: str | None = None) -> Transcript:
    transcript = Transcript(
        text_raw="원본 전사 텍스트",
        text_corrected=corrected,
        language="ko",
        provider="fake",
        provider_model="fake-large",
    )
    return transcript


def _make_summary(content_markdown: str) -> Summary:
    return Summary(
        content_markdown=content_markdown,
        key_points=[],
        concepts=[],
        code_snippets=[],
        action_items=[],
        keywords=[],
        provider="fake",
        provider_model="fake-model",
    )


class TestRenderTxtExport:
    def test_uses_corrected_text_when_available(self) -> None:
        transcript = _make_transcript(corrected="보정된 전사 텍스트")

        assert render_txt_export(transcript) == "보정된 전사 텍스트"

    def test_falls_back_to_raw_when_no_correction(self) -> None:
        transcript = _make_transcript(corrected=None)

        assert render_txt_export(transcript) == "원본 전사 텍스트"


class TestRenderMarkdownExport:
    def test_includes_title_course_date_and_summary_and_transcript(self) -> None:
        transcript = _make_transcript(corrected="보정된 전사 텍스트")
        summary = _make_summary("## 한 줄 요약\n이진 탐색 트리 강의\n\n## 핵심 주제\n없음")

        md = render_markdown_export(
            title="7주차",
            course="자료구조",
            recorded_at=datetime(2026, 8, 20, tzinfo=UTC),
            transcript=transcript,
            summary=summary,
        )

        assert "# 7주차" in md
        assert "자료구조" in md
        assert "2026-08-20" in md
        assert "## 한 줄 요약" in md
        assert "이진 탐색 트리 강의" in md
        assert "## 전사 전문" in md
        assert "보정된 전사 텍스트" in md

    def test_no_course_shows_placeholder(self) -> None:
        transcript = _make_transcript()
        summary = _make_summary("## 한 줄 요약\n요약\n\n## 핵심 주제\n없음")

        md = render_markdown_export(
            title="7주차",
            course=None,
            recorded_at=datetime(2026, 8, 20, tzinfo=UTC),
            transcript=transcript,
            summary=summary,
        )

        assert "(미지정)" in md

    def test_missing_summary_shows_placeholder_not_crash(self) -> None:
        transcript = _make_transcript()

        md = render_markdown_export(
            title="7주차",
            course="자료구조",
            recorded_at=datetime(2026, 8, 20, tzinfo=UTC),
            transcript=transcript,
            summary=None,
        )

        assert "요약이 아직 없습니다" in md
        assert "## 전사 전문" in md


class TestRenderSrtExport:
    def test_srt_timecode_format(self) -> None:
        transcript = _make_transcript()
        transcript.segments = [
            TranscriptSegment(seq=0, start_seconds=0.0, end_seconds=5.2, text="첫 번째 문장"),
            TranscriptSegment(seq=1, start_seconds=5.2, end_seconds=71.834, text="두 번째 문장"),
        ]

        srt = render_srt_export(transcript)

        assert "1\n00:00:00,000 --> 00:00:05,200\n첫 번째 문장\n" in srt
        assert "2\n00:00:05,200 --> 00:01:11,834\n두 번째 문장\n" in srt

    def test_sequence_numbers_start_at_1_and_follow_seq_order(self) -> None:
        transcript = _make_transcript()
        # 일부러 seq 역순으로 추가해도 렌더링은 seq 오름차순을 따라야 한다.
        transcript.segments = [
            TranscriptSegment(seq=1, start_seconds=5.0, end_seconds=10.0, text="나중 문장"),
            TranscriptSegment(seq=0, start_seconds=0.0, end_seconds=5.0, text="먼저 문장"),
        ]

        srt = render_srt_export(transcript)
        blocks = srt.strip().split("\n\n")

        assert blocks[0].startswith("1\n")
        assert "먼저 문장" in blocks[0]
        assert blocks[1].startswith("2\n")
        assert "나중 문장" in blocks[1]

    def test_hour_boundary_formatting(self) -> None:
        transcript = _make_transcript()
        transcript.segments = [
            TranscriptSegment(seq=0, start_seconds=3661.5, end_seconds=3665.0, text="1시간 이후")
        ]

        srt = render_srt_export(transcript)

        assert "01:01:01,500 --> 01:01:05,000" in srt
