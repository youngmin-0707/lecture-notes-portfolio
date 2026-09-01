"""프롬프트 호출 + 파싱 + 형식위반 1회 재요청 (2026-09-01 신규, 복습 문제 자동 생성 기능).

`app/llm/summarizer.py`와 대칭 구조다. 429/5xx/타임아웃 재시도(최대 N회, 지수 백오프)는
이 모듈의 책임이 아니다 — `app/pipeline/quiz.py`가 이 함수 전체를 한 번의 "시도"로 보고
감싼다.
"""

from __future__ import annotations

import logging

from app.core.errors import AppError
from app.llm.base import LlmProvider
from app.llm.prompt import build_retry_prompt
from app.llm.quiz_parsing import parse_quiz_response
from app.llm.quiz_prompt import QUIZ_JSON_SCHEMA
from app.llm.quiz_schema import ParsedQuiz

logger = logging.getLogger("app.llm.quiz_generator")

_RESPONSE_SCHEMA_NAME = "lecture_quiz"


def generate_structured_quiz(provider: LlmProvider, prompt: str) -> ParsedQuiz:
    """`provider.generate(prompt, ...)`를 호출해 구조화된 복습 문제를 얻는다.

    응답이 고정 스키마를 어기면(JSON 파싱 실패 등) 동일 provider로 1회 재요청하고, 그래도
    실패하면 `AppError("LLM_INVALID_RESPONSE")`를 던진다 (재시도 불가로 표시되어 상위
    백오프 재시도 루프가 즉시 최종 실패로 처리한다).

    `provider.generate()`가 던지는 `AppError`(429/5xx/타임아웃 등 재시도 가능한 오류)는
    그대로 전파한다.
    """
    raw = provider.generate(
        prompt, response_schema=QUIZ_JSON_SCHEMA, response_schema_name=_RESPONSE_SCHEMA_NAME
    )
    try:
        return parse_quiz_response(raw)
    except ValueError as first_error:
        logger.warning("LLM quiz response failed schema validation, retrying once: %s", first_error)
        retry_prompt = build_retry_prompt(prompt, previous_error=str(first_error))
        raw_retry = provider.generate(
            retry_prompt,
            response_schema=QUIZ_JSON_SCHEMA,
            response_schema_name=_RESPONSE_SCHEMA_NAME,
        )
        try:
            return parse_quiz_response(raw_retry)
        except ValueError as second_error:
            logger.warning(
                "LLM quiz response failed schema validation again after retry: %s",
                second_error,
            )
            raise AppError("LLM_INVALID_RESPONSE", retryable=False) from second_error
