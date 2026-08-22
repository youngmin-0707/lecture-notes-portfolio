"""요약 JSON 파싱 + 고정 6섹션 마크다운 렌더링 테스트 (T-16, US-05)."""

from __future__ import annotations

import json

import pytest

from app.llm.fake import DEFAULT_VALID_SUMMARY_JSON, make_summary_json
from app.llm.parsing import parse_summary_response, render_markdown

REQUIRED_HEADERS = [
    "## 한 줄 요약",
    "## 핵심 주제",
    "## 개념 정리",
    "## 코드 / 명령어",
    "## 과제 및 공지",
    "## 복습 키워드",
]


class TestParseSummaryResponseSuccess:
    def test_parses_default_valid_json(self) -> None:
        parsed = parse_summary_response(DEFAULT_VALID_SUMMARY_JSON)

        assert parsed.one_line_summary
        assert len(parsed.key_points) >= 3
        assert all(kp.at_seconds is not None for kp in parsed.key_points)
        assert parsed.action_items == []

    def test_strips_markdown_code_fence(self) -> None:
        fenced = f"```json\n{DEFAULT_VALID_SUMMARY_JSON}\n```"
        parsed = parse_summary_response(fenced)
        assert parsed.one_line_summary

    def test_action_items_with_due_date(self) -> None:
        raw = make_summary_json(actionItems=[{"text": "과제 3번 제출", "dueDate": "2026-08-27"}])
        parsed = parse_summary_response(raw)

        assert len(parsed.action_items) == 1
        assert parsed.action_items[0].text == "과제 3번 제출"
        assert parsed.action_items[0].due_date == "2026-08-27"

    def test_action_item_without_due_date(self) -> None:
        raw = make_summary_json(actionItems=[{"text": "다음 주 퀴즈 예정", "dueDate": None}])
        parsed = parse_summary_response(raw)
        assert parsed.action_items[0].due_date is None


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


class TestRenderMarkdownAlwaysHasSixSections:
    def test_all_six_headers_present_for_full_content(self) -> None:
        parsed = parse_summary_response(
            make_summary_json(actionItems=[{"text": "과제 3번 제출", "dueDate": "2026-08-27"}])
        )
        markdown = render_markdown(parsed)

        for header in REQUIRED_HEADERS:
            assert header in markdown

    def test_action_items_section_shows_none_when_empty(self) -> None:
        """US-05: 과제/공지가 없으면 actionItems가 빈 배열이고 본문에 '없음'이 명시된다."""
        parsed = parse_summary_response(make_summary_json(actionItems=[]))
        markdown = render_markdown(parsed)

        for header in REQUIRED_HEADERS:
            assert header in markdown

        action_section = markdown.split("## 과제 및 공지")[1].split("## 복습 키워드")[0]
        assert "없음" in action_section

    def test_key_points_include_timestamp_marker(self) -> None:
        parsed = parse_summary_response(DEFAULT_VALID_SUMMARY_JSON)
        markdown = render_markdown(parsed)
        key_points_section = markdown.split("## 핵심 주제")[1].split("## 개념 정리")[0]
        assert "[" in key_points_section  # 타임스탬프가 대괄호로 병기된다.

    def test_empty_concepts_and_keywords_render_none(self) -> None:
        raw = make_summary_json(concepts=[], keywords=[])
        parsed = parse_summary_response(raw)
        markdown = render_markdown(parsed)

        concepts_section = markdown.split("## 개념 정리")[1].split("## 코드 / 명령어")[0]
        assert "없음" in concepts_section
        keywords_section = markdown.split("## 복습 키워드")[1]
        assert "없음" in keywords_section
