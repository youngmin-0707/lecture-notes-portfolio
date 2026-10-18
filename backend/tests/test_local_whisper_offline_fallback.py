"""`_load_model()`의 오프라인-우선 로딩 로직 유닛 테스트 (T-36).

실제 `faster_whisper`/`ctranslate2`는 무겁고(§2.2 지연 로딩 원칙, §6 NFR) 여기서 임포트하면
안 된다 — `sys.modules`에 가짜 `faster_whisper` 모듈을 심어 `_load_model()` 내부의
`from faster_whisper import WhisperModel`이 가짜를 가져오게 한다. 실제 모델 로드/다운로드
없이 "캐시 있으면 오프라인으로만 로드, 없으면 네트워크로 폴백"이라는 제어 흐름만 검증한다.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.stt import local_whisper as local_whisper_module


@pytest.fixture(autouse=True)
def _clear_model_cache() -> Iterator[None]:
    local_whisper_module._model_cache.clear()
    yield
    local_whisper_module._model_cache.clear()


def _install_fake_faster_whisper(monkeypatch: pytest.MonkeyPatch, whisper_model_cls: type) -> None:
    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = whisper_model_cls
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)


class TestLoadModelOfflineFirst:
    def test_uses_local_files_only_when_cache_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []

        class FakeWhisperModel:
            def __init__(
                self, model_size, *, device, compute_type, download_root, local_files_only=False
            ):
                calls.append(local_files_only)
                if not local_files_only:
                    raise AssertionError("캐시가 있다고 가정했는데 네트워크 폴백을 시도함")

        _install_fake_faster_whisper(monkeypatch, FakeWhisperModel)

        local_whisper_module._load_model("large-v3-turbo", "cpu", "int8", str(tmp_path))

        assert calls == [True]

    def test_falls_back_to_network_when_not_cached_locally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []

        class FakeWhisperModel:
            def __init__(
                self, model_size, *, device, compute_type, download_root, local_files_only=False
            ):
                calls.append(local_files_only)
                if local_files_only:
                    raise RuntimeError("cache miss")

        _install_fake_faster_whisper(monkeypatch, FakeWhisperModel)

        local_whisper_module._load_model("large-v3-turbo", "cpu", "int8", str(tmp_path))

        assert calls == [True, False]

    def test_raises_stt_model_unavailable_when_both_attempts_fail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("boom")

        _install_fake_faster_whisper(monkeypatch, FakeWhisperModel)

        with pytest.raises(AppError) as exc_info:
            local_whisper_module._load_model("large-v3-turbo", "cpu", "int8", str(tmp_path))

        assert exc_info.value.code == "STT_MODEL_UNAVAILABLE"

    def test_successful_offline_load_is_cached_and_not_reloaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []

        class FakeWhisperModel:
            def __init__(
                self, model_size, *, device, compute_type, download_root, local_files_only=False
            ):
                calls.append(local_files_only)

        _install_fake_faster_whisper(monkeypatch, FakeWhisperModel)

        first = local_whisper_module._load_model("large-v3-turbo", "cpu", "int8", str(tmp_path))
        second = local_whisper_module._load_model("large-v3-turbo", "cpu", "int8", str(tmp_path))

        assert first is second
        assert calls == [True]  # 두 번째 호출은 캐시를 써서 WhisperModel을 아예 안 만든다.
