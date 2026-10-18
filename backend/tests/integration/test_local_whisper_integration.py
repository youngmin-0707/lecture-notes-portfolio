"""실제 `faster-whisper` 모델로 전사가 되는지 확인하는 통합 테스트 (T-11).

기본 스위트(`pytest`)에서는 실행되지 않는다 — `large-v3-turbo` 모델은 최초 실행 시
약 1.5GB를 자동 다운로드하고(네트워크 필요), CPU 추론도 수 초~수십 초가 걸려
"전체 스위트가 외부 API 미호출 + 실제 모델 미로드로 수 초 내 완료"(§6)라는 NFR과
정면으로 충돌한다.

실행하려면:
    RUN_REAL_STT_TEST=1 .venv/bin/pytest tests/integration/test_local_whisper_integration.py \
        -m real_model -v
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.stt.local_whisper import LocalWhisperSttProvider, _model_cache

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "ko_sample.wav"

pytestmark = [
    pytest.mark.real_model,
    pytest.mark.skipif(
        not os.environ.get("RUN_REAL_STT_TEST"),
        reason=(
            "실제 Whisper 모델 로드/다운로드가 필요한 느린 테스트. "
            "RUN_REAL_STT_TEST=1 환경변수로 명시적으로 실행해야 한다 (T-11)."
        ),
    ),
]


def test_real_transcription_succeeds_and_model_is_cached(tmp_path) -> None:
    assert FIXTURE_PATH.exists(), f"fixture not found: {FIXTURE_PATH}"

    _model_cache.clear()  # 캐시 재사용(2회차가 더 빠름)을 검증하기 위해 초기화한다.
    download_root = (
        str(tmp_path / "models")
        if os.environ.get("STT_TEST_FRESH_DOWNLOAD")
        else settings.MODEL_CACHE_DIR
    )

    provider = LocalWhisperSttProvider(download_root=download_root)

    progress_calls: list[tuple[float, float]] = []
    started = time.monotonic()
    result = provider.transcribe(
        FIXTURE_PATH,
        language="ko",
        progress_callback=lambda processed, duration: progress_calls.append((processed, duration)),
    )
    first_call_elapsed = time.monotonic() - started

    assert result.text.strip() != ""
    assert len(result.segments) >= 1
    assert result.language == "ko"
    # "이진 탐색 트리" TTS 발화 원문의 핵심 어휘가 인식되는지 느슨하게 확인한다.
    assert "탐색" in result.text or "트리" in result.text
    assert progress_calls, "progress_callback이 최소 1회는 호출되어야 한다 (§3.2)"

    # 두 번째 호출은 모델을 다시 로드하지 않으므로 눈에 띄게 빨라야 한다 (§3.2 "재로딩 금지").
    started = time.monotonic()
    provider.transcribe(FIXTURE_PATH, language="ko")
    second_call_elapsed = time.monotonic() - started

    assert second_call_elapsed < first_call_elapsed
