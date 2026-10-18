"""`SttProvider` 인터페이스 + `FakeSttProvider` 테스트 (T-10).

실제 모델을 전혀 로드하지 않고 성공/실패/타임아웃/진행률 시나리오를 결정론적으로
재현할 수 있음을 확인한다 (§6 테스트성 NFR: 수 초 내 완료).
"""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.stt.base import SttProvider, SttSegment, SttTranscriptionResult
from app.stt.fake import FakeSttProvider


class TestSuccessScenario:
    def test_returns_segments_and_joined_text(self) -> None:
        segments = [
            SttSegment(start=0.0, end=1.0, text="안녕하세요."),
            SttSegment(start=1.0, end=2.0, text="반갑습니다."),
        ]
        provider = FakeSttProvider(segments=segments, elapsed_seconds=0.42)

        result = provider.transcribe("dummy.wav", language="ko")

        assert isinstance(result, SttTranscriptionResult)
        assert result.segments == segments
        assert result.text == "안녕하세요. 반갑습니다."
        assert result.elapsed_seconds == pytest.approx(0.42)
        assert result.language == "ko"

    def test_records_call_arguments(self) -> None:
        provider = FakeSttProvider()

        provider.transcribe("audio/foo.wav", language="ko", initial_prompt="PostgreSQL")

        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call.audio_path == "audio/foo.wav"
        assert call.language == "ko"
        assert call.initial_prompt == "PostgreSQL"

    def test_default_segments_when_not_specified(self) -> None:
        provider = FakeSttProvider()

        result = provider.transcribe("dummy.wav", language="ko")

        assert len(result.segments) > 0
        assert result.text


class TestFailureScenario:
    def test_raises_injected_app_error(self) -> None:
        provider = FakeSttProvider(error=AppError("STT_FAILED"))

        with pytest.raises(AppError) as exc_info:
            provider.transcribe("dummy.wav", language="ko")
        assert exc_info.value.code == "STT_FAILED"

    def test_raises_injected_timeout_error(self) -> None:
        provider = FakeSttProvider(error=TimeoutError("stt timed out"))

        with pytest.raises(TimeoutError):
            provider.transcribe("dummy.wav", language="ko")


class TestProgressScenario:
    def test_progress_callback_invoked_in_order(self) -> None:
        updates = [(0.0, 10.0), (5.0, 10.0), (10.0, 10.0)]
        provider = FakeSttProvider(progress_updates=updates)
        observed: list[tuple[float, float]] = []

        provider.transcribe(
            "dummy.wav", language="ko", progress_callback=lambda p, d: observed.append((p, d))
        )

        assert observed == updates

    def test_progress_callback_invoked_before_failure(self) -> None:
        """실패 직전까지 진행되다 실패하는 시나리오도 재현 가능해야 한다."""
        updates = [(0.0, 10.0), (3.0, 10.0)]
        provider = FakeSttProvider(progress_updates=updates, error=RuntimeError("boom"))
        observed: list[tuple[float, float]] = []

        with pytest.raises(RuntimeError):
            provider.transcribe(
                "dummy.wav",
                language="ko",
                progress_callback=lambda p, d: observed.append((p, d)),
            )

        assert observed == updates

    def test_progress_callback_optional(self) -> None:
        """콜백을 넘기지 않아도 정상 동작해야 한다."""
        provider = FakeSttProvider(progress_updates=[(1.0, 2.0)])

        result = provider.transcribe("dummy.wav", language="ko")

        assert result.text


class TestInterfaceContract:
    def test_fake_is_an_stt_provider(self) -> None:
        assert isinstance(FakeSttProvider(), SttProvider)

    def test_provider_name_and_model_exposed(self) -> None:
        provider = FakeSttProvider(provider_model="fake-large-v3-turbo")

        assert provider.provider_name == "fake"
        assert provider.provider_model == "fake-large-v3-turbo"

    def test_cannot_instantiate_abstract_base_directly(self) -> None:
        with pytest.raises(TypeError):
            SttProvider()  # type: ignore[abstract]
