"""프롬프트 호출 + 파싱 + 형식위반 1회 재요청 (§3.4, T-16).

429/5xx/타임아웃 재시도(최대 3회, 지수 백오프)는 이 모듈의 책임이 아니다 — 그건
`app/pipeline/summarization.py`(T-18)가 `generate_structured_summary()` 전체를 한 번의
"시도"로 보고 감싼다. 이 모듈은 오직 "형식 위반 시 1회 재요청" 규칙만 다룬다.
"""

from __future__ import annotations

import logging

from app.core.errors import AppError
from app.llm.base import LlmProvider
from app.llm.parsing import parse_summary_response
from app.llm.prompt import build_retry_prompt
from app.llm.schema import ParsedSummary

logger = logging.getLogger("app.llm.summarizer")


def generate_structured_summary(provider: LlmProvider, prompt: str) -> ParsedSummary:
    """`provider.generate(prompt)`를 호출해 구조화 요약을 얻는다.

    응답이 §3.4 고정 스키마를 어기면(JSON 파싱 실패 등) 동일 provider로 1회 재요청하고,
    그래도 실패하면 `AppError("LLM_INVALID_RESPONSE")`를 던진다 (재시도 불가로 표시되어
    T-18의 백오프 재시도 루프가 즉시 최종 실패로 처리한다).

    `provider.generate()`가 던지는 `AppError`(429/5xx/타임아웃 등 재시도 가능한 오류)는
    그대로 전파한다 — 이 경우는 "형식 위반"이 아니라 "요청 자체가 실패"한 것이므로 상위
    백오프 루프가 판단해야 한다.
    """
    raw = provider.generate(prompt)
    try:
        return parse_summary_response(raw)
    except ValueError as first_error:
        logger.warning(
            "LLM summary response failed schema validation, retrying once: %s", first_error
        )
        retry_prompt = build_retry_prompt(prompt, previous_error=str(first_error))
        raw_retry = provider.generate(retry_prompt)
        try:
            return parse_summary_response(raw_retry)
        except ValueError as second_error:
            logger.warning(
                "LLM summary response failed schema validation again after retry: %s",
                second_error,
            )
            raise AppError("LLM_INVALID_RESPONSE", retryable=False) from second_error
