"""완전 오프라인 동작 검증 (T-36, US-09, §3.7).

로컬 STT(faster-whisper, 모델 캐시됨) + 로컬 LLM(Ollama)로 업로드→전사→요약 전체
파이프라인을 실행하는 동안 **127.0.0.1/localhost가 아닌 곳으로의 네트워크 연결 시도가
단 한 건도 없는지** 실제로 소켓 레벨에서 감시한다. Wi-Fi를 실제로 끄는 방식 대신
`socket.socket.connect`를 가로채 외부 목적지로의 연결 시도 자체를 예외로 만든다 —
재현 가능하고, 이 머신의 다른 네트워크 사용에 영향을 주지 않으며, faster-whisper나
httpx 클라이언트 라이브러리가 어딘가에 몰래 "연결 확인" 요청을 보내는 것까지 잡아낼 수
있어 Wi-Fi를 끄는 것보다 오히려 더 엄격하다.

기본 스위트에서는 실행되지 않는다 — 실제 캐시된 large-v3-turbo 모델 로드(수 초~수십 초)와
실제 Ollama 생성 요청이 필요해 §6 NFR("전체 스위트가 수 초 내 완료")과 충돌한다.

실행하려면:
    RUN_REAL_STT_TEST=1 .venv/bin/pytest tests/integration/test_offline_mode.py \
        -m real_model -v
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.config import settings
from app.llm.ollama import OllamaLlmProvider
from app.models.enums import SessionStatus
from app.models.session import Session
from app.pipeline.summarization import summarize_session
from app.pipeline.transcription import transcribe_session
from app.stt.local_whisper import LocalWhisperSttProvider, _model_cache

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "ko_sample.wav"

# 오프라인 모드에서 예외적으로 허용되는 목적지 — 전부 이 머신 안에서만 도는 것들이다.
_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}

pytestmark = [
    pytest.mark.real_model,
    pytest.mark.skipif(
        not os.environ.get("RUN_REAL_STT_TEST"),
        reason=(
            "실제 Whisper 모델 로드 + 실제 Ollama 생성이 필요한 느린 테스트. "
            "RUN_REAL_STT_TEST=1 환경변수로 명시적으로 실행해야 한다 (T-36)."
        ),
    ),
]


@contextmanager
def block_external_network() -> Iterator[list[tuple[str, int]]]:
    """`socket.socket.connect()`를 가로채, 127.0.0.1/localhost가 아닌 목적지로의 연결
    시도를 전부 막고 기록한다. 실제 Wi-Fi를 끄지 않고도 "외부 요청 0건"을 강제·감시한다.
    """
    blocked: list[tuple[str, int]] = []
    original_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address, *args, **kwargs):  # noqa: ANN001
        host = address[0] if isinstance(address, tuple) else address
        if host not in _ALLOWED_HOSTS:
            port = address[1] if isinstance(address, tuple) and len(address) > 1 else -1
            blocked.append((str(host), int(port)))
            raise ConnectionError(
                f"오프라인 모드 위반: 외부 네트워크 연결 시도 감지됨 (host={host}, port={port})"
            )
        return original_connect(self, address, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    try:
        yield blocked
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="오프라인 검증 세션",
        course="검증",
        status=SessionStatus.UPLOADED.value,
        source="UPLOAD",
        audio_path=str(FIXTURE_PATH),
        original_filename="ko_sample.wav",
        mime_type="audio/wav",
        file_size_bytes=FIXTURE_PATH.stat().st_size if FIXTURE_PATH.exists() else 0,
        duration_seconds=None,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


def test_full_pipeline_offline_produces_done_with_zero_external_calls(db_session) -> None:
    assert FIXTURE_PATH.exists(), f"fixture not found: {FIXTURE_PATH}"

    _model_cache.clear()

    session = _make_session()
    db_session.add(session)
    db_session.flush()

    with block_external_network() as blocked_calls:
        stt_provider = LocalWhisperSttProvider(download_root=settings.MODEL_CACHE_DIR)
        session = transcribe_session(db_session, session, stt_provider)
        assert session.status == SessionStatus.TRANSCRIBED.value, (
            f"전사 실패: {session.error_code} {session.error_message}"
        )

        llm_provider = OllamaLlmProvider()
        session = summarize_session(db_session, session, llm_provider)
        assert session.status == SessionStatus.DONE.value, (
            f"요약 실패: {session.error_code} {session.error_message}"
        )

    assert blocked_calls == [], (
        f"오프라인 모드 위반: 외부 연결 시도 {len(blocked_calls)}건 감지됨: {blocked_calls}"
    )
