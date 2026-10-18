"""복습 문제 LLM JSON 응답 파싱 (2026-09-01 신규, 복습 문제 자동 생성 기능).

`app/llm/parsing.py`(요약)와 대칭 구조다 — 형식이 어긋난 응답에는 항상 `ValueError`를
던지고, 호출부(`app/llm/quiz_generator.py`)가 "형식 위반 → 1회 재요청" 신호로 쓴다.
"""

from __future__ import annotations

import json
import re

from app.llm.quiz_schema import ParsedQuiz, QuizQuestion

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n?|\n?```$")

_MIN_QUESTIONS = 1


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _CODE_FENCE_RE.sub("", stripped).strip()
    return stripped


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' 필드는 문자열이어야 합니다.")
    if not value.strip():
        raise ValueError(f"'{field_name}' 필드가 비어 있습니다.")
    return value


def _parse_questions(raw: object) -> list[QuizQuestion]:
    if not isinstance(raw, list):
        raise ValueError("'questions' 필드는 배열이어야 합니다.")
    if len(raw) < _MIN_QUESTIONS:
        raise ValueError("'questions' 필드에 최소 1개의 문제가 있어야 합니다.")
    questions: list[QuizQuestion] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("'questions' 항목은 객체여야 합니다.")
        question = _require_str(item.get("question"), "questions[].question")
        answer = _require_str(item.get("answer"), "questions[].answer")
        questions.append(QuizQuestion(question=question, answer=answer))
    return questions


def parse_quiz_response(raw_text: str) -> ParsedQuiz:
    """LLM 원문 응답을 `ParsedQuiz`로 파싱한다.

    JSON 파싱 실패, 필수 필드 누락/타입 불일치, 빈 문제 목록 등 어떤 형식 위반이든
    `ValueError`를 던진다.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("LLM 응답이 비어 있습니다.")

    candidate = _strip_code_fence(raw_text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"유효한 JSON이 아닙니다: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("응답 최상위는 JSON 객체여야 합니다.")

    questions = _parse_questions(data.get("questions", []))
    return ParsedQuiz(questions=questions)
