"""복습 문제 고정 출력 스키마 (2026-09-01 신규, 복습 문제 자동 생성 기능).

LLM 원문 응답(JSON)을 파싱한 결과를 담는 불변 dataclass. `app/llm/schema.py`의
`ParsedSummary`와 대칭 구조다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QuizQuestion:
    """복습 문제 1개 — 질문과, 강의 내용에 근거한 정답 설명."""

    question: str
    answer: str


@dataclass(frozen=True)
class ParsedQuiz:
    """LLM 응답을 파싱한 결과."""

    questions: list[QuizQuestion] = field(default_factory=list)
