"""요약 JSON 파싱 + 마크다운 렌더링 테스트 (T-16, US-05; 2026-08-29 자유형식 본문 개정)."""

from __future__ import annotations

import json

import pytest

from app.llm.fake import DEFAULT_VALID_SUMMARY_JSON, make_summary_json
from app.llm.parsing import parse_summary_response, render_markdown

FIXED_HEADERS = ["## 한 줄 요약", "## 핵심 주제", "## 복습 키워드"]


class TestParseSummaryResponseSuccess:
    def test_parses_default_valid_json(self) -> None:
        parsed = parse_summary_response(DEFAULT_VALID_SUMMARY_JSON)

        assert parsed.one_line_summary
        assert len(parsed.key_points) >= 3
        assert all(kp.at_seconds is not None for kp in parsed.key_points)
        assert parsed.detailed_notes

    def test_strips_markdown_code_fence(self) -> None:
        fenced = f"```json\n{DEFAULT_VALID_SUMMARY_JSON}\n```"
        parsed = parse_summary_response(fenced)
        assert parsed.one_line_summary

    def test_detailed_notes_preserved_verbatim(self) -> None:
        raw = make_summary_json(detailedNotes="1. 첫 섹션\n2. 두 번째 섹션 (강사 당부사항)")
        parsed = parse_summary_response(raw)

        assert parsed.detailed_notes == "1. 첫 섹션\n2. 두 번째 섹션 (강사 당부사항)"


class TestParseSummaryResponseFormatViolations:
    def test_raises_value_error_on_invalid_json(self) -> None:
        with pytest.raises(ValueError):
            parse_summary_response("이것은 JSON이 아닙니다")

    def test_raises_value_error_when_top_level_is_not_object(self) -> None:
        with pytest.raises(ValueError):
            parse_summary_response("[1, 2, 3]")

    def test_raises_value_error_when_one_line_summary_missing(self) -> None:
        data = json.loads(DEFAULT_VALID_SUMMARY_JSON)
        del data["oneLineSummary"]
        with pytest.raises(ValueError):
            parse_summary_response(json.dumps(data))

    def test_raises_value_error_when_detailed_notes_missing(self) -> None:
        data = json.loads(DEFAULT_VALID_SUMMARY_JSON)
        del data["detailedNotes"]
        with pytest.raises(ValueError):
            parse_summary_response(json.dumps(data))

    def test_raises_value_error_when_detailed_notes_empty(self) -> None:
        raw = make_summary_json(detailedNotes="")
        with pytest.raises(ValueError):
            parse_summary_response(raw)

    def test_raises_value_error_when_key_point_missing_at_seconds(self) -> None:
        raw = make_summary_json(keyPoints=[{"text": "타임스탬프 없는 항목"}])
        with pytest.raises(ValueError):
            parse_summary_response(raw)

    def test_raises_value_error_when_key_points_not_a_list(self) -> None:
        raw = make_summary_json(keyPoints="핵심 주제입니다")
        with pytest.raises(ValueError):
            parse_summary_response(raw)

    def test_raises_value_error_on_empty_string(self) -> None:
        with pytest.raises(ValueError):
            parse_summary_response("")


class TestRenderMarkdown:
    def test_fixed_headers_present(self) -> None:
        parsed = parse_summary_response(DEFAULT_VALID_SUMMARY_JSON)
        markdown = render_markdown(parsed)

        for header in FIXED_HEADERS:
            assert header in markdown

    def test_detailed_notes_appears_verbatim_in_body(self) -> None:
        raw = make_summary_json(detailedNotes="1. 첫 섹션\n💡 왜 그런가요? → 이래서예요.")
        parsed = parse_summary_response(raw)
        markdown = render_markdown(parsed)

        assert "1. 첫 섹션\n💡 왜 그런가요? → 이래서예요." in markdown

    def test_key_points_include_timestamp_marker(self) -> None:
        parsed = parse_summary_response(DEFAULT_VALID_SUMMARY_JSON)
        markdown = render_markdown(parsed)
        key_points_section = markdown.split("## 핵심 주제")[1].split(parsed.detailed_notes)[0]
        assert "[" in key_points_section  # 타임스탬프가 대괄호로 병기된다.

    def test_empty_key_points_and_keywords_render_none(self) -> None:
        raw = make_summary_json(keyPoints=[], keywords=[])
        parsed = parse_summary_response(raw)
        markdown = render_markdown(parsed)

        key_points_section = markdown.split("## 핵심 주제")[1].split(parsed.detailed_notes)[0]
        assert "없음" in key_points_section
        keywords_section = markdown.split("## 복습 키워드")[1]
        assert "없음" in keywords_section
