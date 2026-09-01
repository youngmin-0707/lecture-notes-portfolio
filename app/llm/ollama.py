"""로컬 Ollama HTTP API 구현체 (T-17, §0 D5/D13, §3.4).

CLI를 shell-out하지 않고 반드시 HTTP API로 통신한다 — CLI 바이너리는 PATH에 없을 수 있고
(macOS 앱 번들 내부에만 존재), 서버는 이미 별도로 기동되어 있다.

- `/api/chat`을 쓴다(`/api/generate`가 아니다). 이 Ollama 빌드(0.32.15 기준 실측)에서는
  `/api/generate` + `think: true` + `format: "json"`을 같이 쓰면 JSON 문법 제약이 처음부터
  걸려 모델이 `<think>` 단계 자체를 건너뛰고 빈 `"{}"`만 즉시 반환하는 버그가 있다(2026-08-29
  확인). `/api/chat`은 같은 조합에서 `message.thinking`과 `message.content`(JSON)를 모두
  정상적으로 채운다.
- `keep_alive`를 요청마다 짧게(`settings.OLLAMA_KEEP_ALIVE`, 기본 `"30s"`) 넘겨 요약 완료 후
  빠르게 모델이 메모리에서 풀리게 한다 (§0 D13, §3.4 Provider 정책).
- `think: settings.OLLAMA_THINK`(기본 `True`)로 reasoning 모델(qwen3)의 사고 과정을 켜둔다.
  `think=False`가 더 빠르지만 뭉뚱그려진 표면적 요약이 나오는 경향이 있어 기본을 켜는 쪽으로
  바꿨다(2026-08-29).
- `temperature: settings.OLLAMA_TEMPERATURE`(기본 0.3)로 Ollama 기본값(~0.8)보다 낮게 고정해
  사실 기반 구조화 요약의 재현성을 높인다.
- `options.num_ctx`(기본 8192)로 컨텍스트 길이를 넉넉히 확보한다 (§3.4, T-15/T-21 이전 임시
  여유분).
- 로컬 API이므로 오프라인 모드(US-09)에서도 정상 동작한다 — 외부 네트워크 요청이 없다.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.llm.base import LlmProvider

logger = logging.getLogger("app.llm.ollama")


class OllamaLlmProvider(LlmProvider):
    """로컬 Ollama `/api/chat` 어댑터."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        keep_alive: str | None = None,
        num_ctx: int | None = None,
        timeout_seconds: float | None = None,
        think: bool | None = None,
        temperature: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self._model = model or settings.LLM_MODEL
        self._keep_alive = keep_alive if keep_alive is not None else settings.OLLAMA_KEEP_ALIVE
        self._num_ctx = num_ctx or settings.OLLAMA_NUM_CTX
        self._timeout_seconds = timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS
        self._think = think if think is not None else settings.OLLAMA_THINK
        self._temperature = temperature if temperature is not None else settings.OLLAMA_TEMPERATURE

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def provider_model(self) -> str:
        return self._model

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "think": self._think,
            "keep_alive": self._keep_alive,
            "options": {"num_ctx": self._num_ctx, "temperature": self._temperature},
        }

        try:
            response = httpx.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout_seconds,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Ollama 데몬이 기동되어 있지 않음 — 재시도로 해결되지 않는다.
            raise AppError("LLM_NOT_CONFIGURED", retryable=False) from exc
        except httpx.TimeoutException as exc:
            raise AppError("LLM_FAILED", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise AppError("LLM_FAILED", retryable=True) from exc

        if response.status_code == 429:
            raise AppError("LLM_QUOTA_EXCEEDED", retryable=True)
        if response.status_code == 404:
            # 모델이 pull되어 있지 않은 등 사용 불가 상태 — 재시도로 해결되지 않는다.
            raise AppError("LLM_NOT_CONFIGURED", retryable=False)
        if response.status_code >= 500:
            raise AppError("LLM_FAILED", retryable=True)
        if response.status_code >= 400:
            # 프롬프트/요청 형식 오류 등 — 재시도해도 동일하게 실패한다 (§3.4 4xx는 즉시 실패).
            raise AppError("LLM_FAILED", retryable=False)

        try:
            data = response.json()
        except ValueError as exc:
            raise AppError("LLM_INVALID_RESPONSE", retryable=False) from exc

        message = data.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise AppError("LLM_INVALID_RESPONSE", retryable=False)

        logger.info(
            "Ollama generate succeeded: model=%s prompt_length=%d response_length=%d",
            self._model,
            len(prompt),
            len(text),
        )
        return text
