"""OpenAI Responses API 기반 LLM Provider (요약 엔진 클라우드 전환, 2026-08-29).

로컬 Ollama(qwen3:14b) 대신 클라우드 LLM(OpenAI)으로 요약 단계만 옮기기 위한 두 번째
`LlmProvider` 구현체다 (`app/llm/base.py`가 규정한 "설정 한 줄로 요약 엔진을 갈아끼울 수
있어야 한다"는 설계를 그대로 활용). 로컬 STT(faster-whisper)는 그대로 오프라인으로 남고
요약 단계에서만 인터넷 연결과 API 비용이 발생한다.

- Ollama 로컬 실행 시 24GB 통합 메모리에서 STT+LLM(qwen3:14b, think:true)을 같이 돌리면
  메모리 압박(swap 발생)이 관측됐고, `think:true`를 켠 뒤로는 스키마 위반(재요약 실패)도
  실제로 발생했다 — 이 두 문제를 함께 해결하기 위한 전환이다.
- Responses API(`client.responses.create`)의 `text.format` structured outputs를 써서
  JSON 스키마를 서버가 강제한다(`strict: True`). Ollama의 느슨한 `format:"json"`과 달리
  스키마 위반 자체가 구조적으로 발생하지 않아, `app/llm/summarizer.py`의 "형식 위반 1회
  재요청" 경로를 사실상 안 타게 된다.
- 스키마는 `app/llm/prompt.py`가 프롬프트에 서술하는 5개 필드(`suggestedTitle`/
  `oneLineSummary`/`keyPoints`/`keywords`/`detailedNotes`)와 1:1 대응한다 — 필드가 갈라지면
  `parse_summary_response()`가 깨지므로 두 곳을 함께 바꿀 것.
"""

from __future__ import annotations

import logging

import openai

from app.core.config import settings
from app.core.errors import AppError
from app.llm.base import LlmProvider

logger = logging.getLogger("app.llm.openai_provider")

_SUMMARY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestedTitle": {
            "type": "string",
            "description": (
                "세션 목록에서 이 강의를 구별할 수 있는 짧고 구체적인 제목(10~20자 내외). "
                "'강의 요약'처럼 뭉뚱그린 제목은 안 된다."
            ),
        },
        "oneLineSummary": {"type": "string"},
        "keyPoints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "atSeconds": {"type": "number"},
                },
                "required": ["text", "atSeconds"],
                "additionalProperties": False,
            },
        },
        "keywords": {"type": "array", "items": {"type": "string"}},
        "detailedNotes": {
            "type": "string",
            "description": (
                "강의 내용에 맞게 자유롭게 구성한 마크다운 본문. 섹션 개수/제목은 고정되지 "
                "않으며, 초보자가 이해할 수 있도록 예시·비유·번호 목록을 적극 활용한다."
            ),
        },
    },
    "required": ["suggestedTitle", "oneLineSummary", "keyPoints", "keywords", "detailedNotes"],
    "additionalProperties": False,
}


class OpenAiLlmProvider(LlmProvider):
    """OpenAI Responses API 어댑터."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        resolved_key = api_key or (
            settings.OPENAI_API_KEY.get_secret_value() if settings.OPENAI_API_KEY else None
        )
        self._model = model or settings.OPENAI_MODEL
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.OPENAI_TIMEOUT_SECONDS
        )
        # 키가 없어도 SDK 생성자는 실패하지 않는다(빈 문자열로 대체) — 실제 실패는 첫 호출 시
        # AuthenticationError로 드러나며, 아래 generate()에서 AppError로 매핑한다.
        self._client = openai.OpenAI(api_key=resolved_key, timeout=self._timeout_seconds)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def provider_model(self) -> str:
        return self._model

    def generate(self, prompt: str) -> str:
        try:
            response = self._client.responses.create(
                model=self._model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "lecture_summary",
                        "schema": _SUMMARY_JSON_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except openai.AuthenticationError as exc:
            raise AppError("LLM_NOT_CONFIGURED", retryable=False) from exc
        except openai.RateLimitError as exc:
            raise AppError("LLM_QUOTA_EXCEEDED", retryable=True) from exc
        except openai.InternalServerError as exc:
            raise AppError("LLM_FAILED", retryable=True) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise AppError("LLM_FAILED", retryable=True) from exc
        except openai.APIStatusError as exc:
            # 그 외 4xx(BadRequestError/PermissionDeniedError/NotFoundError 등) — 재시도해도
            # 동일하게 실패한다 (§3.4 4xx는 즉시 실패 규칙과 동일하게 적용).
            raise AppError("LLM_FAILED", retryable=False) from exc

        text = response.output_text
        if not isinstance(text, str) or not text:
            raise AppError("LLM_INVALID_RESPONSE", retryable=False)

        logger.info(
            "OpenAI generate succeeded: model=%s prompt_length=%d response_length=%d",
            self._model,
            len(prompt),
            len(text),
        )
        return text
