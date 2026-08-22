"""`LlmProvider` 추상 인터페이스 (§2.2, §3.4, T-14).

`SttProvider`(§2.2 `app/stt/base.py`)와 대칭 구조다: `pipeline/`·`app/llm/summarizer.py`는
이 인터페이스에만 의존하고 구체 구현(`ollama.py`, `fake.py`, 추후 `gemini.py`/`groq.py`)을
알지 못한다. 설정 한 줄로 요약 엔진을 갈아끼울 수 있어야 한다는 것이 이 프로젝트의 핵심 구조적
결정이다 (§0.2).

인터페이스는 의도적으로 얇다 — "프롬프트 문자열을 보내고 원문 텍스트 응답을 받는다"만 책임진다.
프롬프트 구성(`app/llm/prompt.py`)과 출력 스키마 파싱·형식위반 재요청(`app/llm/summarizer.py`)은
Provider가 아니라 그 위 계층의 책임이다 (STT의 세그먼트 검증이 `pipeline/transcription.py`에
있는 것과 동일한 설계 원칙).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LlmProvider(ABC):
    """요약 LLM 엔진 어댑터 인터페이스 (§0.2, §2.2)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """`summaries.provider`에 저장될 어댑터 식별자 (예: `ollama`)."""

    @property
    @abstractmethod
    def provider_model(self) -> str:
        """`summaries.provider_model`에 저장될 모델 식별자 (예: `qwen3:8b`)."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """프롬프트를 LLM에 보내고 원문 텍스트 응답을 반환한다.

        구현체는 실패를 항상 `app.core.errors.AppError`로 던져야 한다 (§5.1 에러 코드 규약).
        재시도 가능 여부(§3.4: 429/5xx/타임아웃만 재시도, 4xx는 즉시 실패)는
        `AppError(retryable=...)`로 표시한다:

        - `LLM_NOT_CONFIGURED` (재시도 불가): 엔진이 기동되지 않았거나 설정되지 않음.
        - `LLM_QUOTA_EXCEEDED` (재시도 가능): 429.
        - `LLM_FAILED` (5xx/타임아웃이면 재시도 가능, 그 외 4xx면 재시도 불가).

        `pipeline/summarization.py`(T-18)는 `retryable=True`인 경우에만 지수 백오프로
        재시도한다.
        """
