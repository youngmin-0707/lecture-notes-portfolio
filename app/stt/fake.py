"""`SttProvider`의 결정론적 Fake 구현체 (T-10).

실제 모델을 로드하지 않고 성공/실패/타임아웃/진행률 시나리오를 생성자 인자로 주입해
재현할 수 있다. `pipeline/`·API 테스트는 이 Fake를 사용해 실제 Whisper 없이 수 초 안에
전체 흐름을 검증한다 (§6 테스트성 NFR).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.stt.base import ProgressCallback, SttProvider, SttSegment, SttTranscriptionResult

DEFAULT_FAKE_SEGMENTS: list[SttSegment] = [
    SttSegment(start=0.0, end=2.5, text="오늘은 이진 탐색 트리에 대해 알아보겠습니다."),
    SttSegment(start=2.5, end=5.0, text="먼저 삽입 연산부터 보겠습니다."),
]


@dataclass
class RecordedCall:
    """`transcribe()` 호출 인자를 기록해 테스트에서 검증할 수 있게 한다."""

    audio_path: str
    language: str
    initial_prompt: str | None


class FakeSttProvider(SttProvider):
    """성공/실패/타임아웃/진행률을 결정론적으로 재현하는 Fake `SttProvider`.

    Args:
        segments: 성공 시 반환할 세그먼트 목록. 미지정 시 `DEFAULT_FAKE_SEGMENTS`.
        elapsed_seconds: 성공 시 반환할 소요 시간(초).
        provider_model: `transcripts.provider_model`에 저장될 값.
        error: 지정하면 `transcribe()`가 이 예외를 그대로 던진다 (실패/타임아웃 시나리오).
            예: `TimeoutError("...")`, `AppError("STT_FAILED")`.
        progress_updates: 지정하면 `progress_callback`에 순서대로 전달한다
            (성공/실패 여부와 무관하게 먼저 호출된다 — 실패 직전까지 진행되다 실패하는
            시나리오도 재현 가능).
    """

    def __init__(
        self,
        *,
        segments: list[SttSegment] | None = None,
        elapsed_seconds: float = 0.01,
        provider_model: str = "fake-model",
        error: BaseException | None = None,
        progress_updates: list[tuple[float, float]] | None = None,
    ) -> None:
        self._segments = list(segments) if segments is not None else list(DEFAULT_FAKE_SEGMENTS)
        self._elapsed_seconds = elapsed_seconds
        self._provider_model = provider_model
        self._error = error
        self._progress_updates = progress_updates or []
        self.calls: list[RecordedCall] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def provider_model(self) -> str:
        return self._provider_model

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str,
        initial_prompt: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SttTranscriptionResult:
        self.calls.append(
            RecordedCall(
                audio_path=str(audio_path), language=language, initial_prompt=initial_prompt
            )
        )

        if progress_callback is not None:
            for processed_seconds, duration_seconds in self._progress_updates:
                progress_callback(processed_seconds, duration_seconds)

        if self._error is not None:
            raise self._error

        text = " ".join(segment.text for segment in self._segments)
        return SttTranscriptionResult(
            text=text,
            segments=list(self._segments),
            elapsed_seconds=self._elapsed_seconds,
            language=language,
        )
