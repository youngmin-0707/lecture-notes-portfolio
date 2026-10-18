"""복습 문제 JSON 파싱 테스트 (2026-09-01, 복습 문제 자동 생성 기능)."""

from __future__ import annotations

import json

import pytest

from app.llm.fake import DEFAULT_VALID_QUIZ_JSON, make_quiz_json
from app.llm.quiz_parsing import parse_quiz_response


class TestParseQuizResponseSuccess:
    def test_parses_default_valid_json(self) -> None:
        parsed = parse_quiz_response(DEFAULT_VALID_QUIZ_JSON)

        assert len(parsed.questions) >= 1
        assert all(q.question and q.answer for q in parsed.questions)

    def test_strips_markdown_code_fence(self) -> None:
        fenced = f"```json\n{DEFAULT_VALID_QUIZ_JSON}\n```"
        parsed = parse_quiz_response(fenced)
        assert len(parsed.questions) >= 1


class TestParseQuizResponseFormatViolations:
    def test_raises_value_error_on_invalid_json(self) -> None:
        with pytest.raises(ValueError):
            parse_quiz_response("이것은 JSON이 아닙니다")

    def test_raises_value_error_when_top_level_is_not_object(self) -> None:
        with pytest.raises(ValueError):
            parse_quiz_response("[1, 2, 3]")

    def test_raises_value_error_when_questions_missing(self) -> None:
        with pytest.raises(ValueError):
            parse_quiz_response(json.dumps({}))

    def test_raises_value_error_when_questions_empty(self) -> None:
        raw = make_quiz_json(questions=[])
        with pytest.raises(ValueError):
            parse_quiz_response(raw)

    def test_raises_value_error_when_question_missing_answer(self) -> None:
        raw = make_quiz_json(questions=[{"question": "질문만 있음"}])
        with pytest.raises(ValueError):
            parse_quiz_response(raw)

    def test_raises_value_error_when_questions_not_a_list(self) -> None:
        raw = make_quiz_json(questions="문제 목록입니다")
        with pytest.raises(ValueError):
            parse_quiz_response(raw)

    def test_raises_value_error_on_empty_string(self) -> None:
        with pytest.raises(ValueError):
            parse_quiz_response("")
