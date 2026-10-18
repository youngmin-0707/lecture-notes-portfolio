"""`SttProvider` 추상 인터페이스 (§2.2, §3.2, T-10).

`pipeline/`은 이 인터페이스에만 의존하고 구체 구현(`local_whisper.py`, `fake.py`, 추후
`groq.py` 등)을 알지 못한다 (§2.2 설계 원칙). 설정 한 줄로 STT 엔진을 갈아끼울 수 있어야
한다는 것이 이 프로젝트의 핵심 구조적 결정이다 (§0.2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# 진행률 콜백: (processed_seconds, duration_seconds) -> None (§3.2 "세그먼트 단위로 갱신").
ProgressCallback = Callable[[float, float], None]


@dataclass(frozen=True)
class SttSegment:
    """전사의 시간 구간 (§2.3 `transcript_segments`와 1:1 대응)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SttTranscriptionResult:
    """`SttProvider.transcribe()`의 반환값 — 전체 텍스트 + 세그먼트 + 소요 시간."""

    text: str
    segments: list[SttSegment] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    language: str = "ko"


class SttProvider(ABC):
    """음성 인식 엔진 어댑터 인터페이스 (§0.2, §2.2)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """`transcripts.provider`에 저장될 어댑터 식별자 (예: `local_whisper`)."""

    @property
    @abstractmethod
    def provider_model(self) -> str:
        """`transcripts.provider_model`에 저장될 모델 식별자 (예: `large-v3-turbo`)."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str,
        initial_prompt: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SttTranscriptionResult:
        """오디오 파일을 전사한다.

        Args:
            audio_path: 로컬 오디오 파일 경로.
            language: 언어 코드 (§0 D10: 이 프로젝트에서는 항상 "ko").
            initial_prompt: 용어집 바이어싱용 프롬프트 (§3.3). 지금 단계에서는 `None`이어도 된다.
            progress_callback: 세그먼트가 처리될 때마다 `(processed_seconds, duration_seconds)`로
                호출된다 (§3.2). 제공되지 않으면 호출하지 않아도 된다.

        Returns:
            전체 텍스트, 세그먼트 목록, 소요 시간을 담은 `SttTranscriptionResult`.

        Raises:
            실패 시 예외를 던진다 (구현체마다 구체적인 예외 타입은 다를 수 있다).
            `pipeline/`은 어떤 예외든 실패로 간주해 세션을 `FAILED`로 전이시킨다.
        """
