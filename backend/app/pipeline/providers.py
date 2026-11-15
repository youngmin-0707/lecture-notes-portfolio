"""설정에 따라 실제 `SttProvider`/`LlmProvider` 구현체를 조립한다 (T-19).

`pipeline/orchestration.py`와 API 라우터가 이 모듈을 통해서만 구체 구현을 얻는다 — 라우터가
`LocalWhisperSttProvider`/`OllamaLlmProvider`를 직접 import하지 않게 해서, 나중에 무료 티어
어댑터(T-29)를 추가해도 호출부를 바꾸지 않아도 된다 (§0.2, §2.2).
"""

from __future__ import annotations

from app.core.config import settings
from app.core.errors import AppError
from app.llm.base import LlmProvider
from app.llm.ollama import OllamaLlmProvider
from app.llm.openai_provider import OpenAiLlmProvider
from app.stt.base import SttProvider
from app.stt.local_whisper import LocalWhisperSttProvider


def build_stt_provider(model: str | None = None) -> SttProvider:
    """`settings.STT_PROVIDER`(이번 라운드는 `local_whisper`만 지원)에 따라 조립한다."""
    provider_name = settings.STT_PROVIDER
    if provider_name != "local_whisper":
        raise AppError(
            "STT_MODEL_UNAVAILABLE",
            message=f"지원하지 않는 STT provider입니다: {provider_name}",
        )
    return LocalWhisperSttProvider(model_size=model, isolate_process=True)


def build_llm_provider(name: str | None = None) -> LlmProvider:
    """`name`(요청 바디의 `llmProvider`) 또는 `settings.LLM_PROVIDER`로 조립한다.

    `ollama`(로컬)와 `openai`(클라우드, 2026-08-29 추가)를 지원한다.
    """
    provider_name = (name or settings.LLM_PROVIDER).lower()
    if provider_name == "ollama":
        return OllamaLlmProvider()
    if provider_name == "openai":
        return OpenAiLlmProvider()
    raise AppError(
        "LLM_NOT_CONFIGURED",
        message=f"지원하지 않는 LLM provider입니다: {provider_name}",
    )
