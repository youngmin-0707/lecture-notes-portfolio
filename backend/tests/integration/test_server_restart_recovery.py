"""실제 서버 프로세스를 재시작해 복구 스윕을 검증한다 (T-37, US-10, §3.6).

`tests/test_recovery_sweep.py`는 이미 `sweep_interrupted_sessions()`와 서버 lifespan 훅을
단위/인프로세스 수준에서 검증한다. 이 파일은 그보다 한 단계 더 실제에 가깝게 — **진짜
uvicorn 프로세스를 띄우고, 강제 종료하고, 다시 띄워서** 복구가 실제로 동작하는지 확인한다.

기본 스위트에서는 실행되지 않는다 (uvicorn 서브프로세스 기동 + 포트 대기만으로도 수 초가
걸리고, 두 번째 테스트는 실제 faster-whisper + Ollama까지 필요해 훨씬 느리다). §6 NFR
("전체 스위트가 외부 API 미호출 + 실제 모델 미로드로 수 초 내 완료")과 충돌하기 때문이다.

실행하려면:
    RUN_SERVER_RESTART_TEST=1 .venv/bin/pytest \
        tests/integration/test_server_restart_recovery.py -m server_restart -v

(두 번째 테스트까지 돌리려면 로컬에 large-v3-turbo가 캐시돼 있고 Ollama가 127.0.0.1:11434에서
LLM_MODEL을 서빙 중이어야 한다 — 이 저장소의 기본 개발 환경과 동일하다.)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

pytestmark = [
    pytest.mark.server_restart,
    pytest.mark.skipif(
        not os.environ.get("RUN_SERVER_RESTART_TEST"),
        reason=(
            "실제 uvicorn 프로세스를 띄우고 강제종료/재기동하는 느린 테스트. "
            "RUN_SERVER_RESTART_TEST=1 환경변수로 명시적으로 실행해야 한다 (T-37)."
        ),
    ),
]


def _alembic_upgrade(database_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def _start_server(
    *, database_url: str, audio_dir: Path, port: int, log_path: Path
) -> subprocess.Popen:
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "AUDIO_STORAGE_DIR": str(audio_dir),
        # 이미 캐시된 실제 모델을 재사용한다 — 새로 받지 않는다.
        "MODEL_CACHE_DIR": str(BACKEND_DIR / "data" / "models"),
        "BIND_PORT": str(port),
    }
    log_file = log_path.open("w")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def _wait_until_ready(port: int, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.5)
    raise TimeoutError(f"server on port {port} did not become ready: {last_error}")


def _wait_until_status_is(
    port: int, session_id: str, target_statuses: set[str], *, timeout: float = 180.0
) -> dict:
    deadline = time.monotonic() + timeout
    body = {}
    while time.monotonic() < deadline:
        response = httpx.get(f"http://127.0.0.1:{port}/api/v1/sessions/{session_id}", timeout=5.0)
        body = response.json()
        if body.get("status") in target_statuses:
            return body
        time.sleep(2.0)
    raise TimeoutError(f"session {session_id} did not reach {target_statuses}: last body={body}")


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    db_path = tmp_path / "restart_test.db"
    url = f"sqlite:///{db_path}"
    _alembic_upgrade(url)
    return url


def test_stale_processing_row_marked_interrupted_on_startup(
    tmp_path: Path, sqlite_url: str
) -> None:
    """서버가 죽기 직전 SUMMARIZING이었던 세션이, 재기동 시 FAILED(INTERRUPTED)로 복구된다.

    실제 STT/LLM을 부르지 않고 DB에 미리 "처리 중이었던" 행을 심어 서버가 막 죽었다가
    다시 켜진 상황을 재현한다 — 검증 대상은 lifespan 복구 훅이 실제 프로세스 기동 시
    진짜로 동작하는지 그 자체다.
    """
    engine = sa.create_engine(sqlite_url, future=True)
    session_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO sessions (id, title, course, status, source, audio_path, "
                "original_filename, mime_type, file_size_bytes, duration_seconds, "
                "recorded_at, created_at, updated_at) VALUES "
                "(:id, :title, :course, 'SUMMARIZING', 'UPLOAD', :audio_path, 'x.wav', "
                "'audio/wav', 100, 3.0, :now, :now, :now)"
            ),
            {
                "id": session_id,
                "title": "T-37 stale row",
                "course": "검증",
                "audio_path": str(tmp_path / "does-not-matter.upload"),
                "now": now,
            },
        )
    engine.dispose()

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    port = 8768
    log_path = tmp_path / "server.log"
    proc = _start_server(database_url=sqlite_url, audio_dir=audio_dir, port=port, log_path=log_path)
    try:
        _wait_until_ready(port)
        response = httpx.get(f"http://127.0.0.1:{port}/api/v1/sessions/{session_id}", timeout=5.0)
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["errorCode"] == "INTERRUPTED"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.real_model
@pytest.mark.skipif(
    not os.environ.get("RUN_REAL_STT_TEST"),
    reason="실제 faster-whisper + Ollama가 모두 필요하다. RUN_REAL_STT_TEST=1도 함께 설정할 것.",
)
def test_real_crash_mid_transcription_recovers_and_completes_on_restart(
    tmp_path: Path, sqlite_url: str
) -> None:
    """진짜로 전사 중인 프로세스를 SIGKILL로 죽이고, 재기동 후 복구→재실행→완료까지 확인한다."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    port = 8769

    wav_path = tmp_path / "sample.wav"
    with wave.open(str(wav_path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 16000 * 3)

    log1 = tmp_path / "server1.log"
    proc1 = _start_server(database_url=sqlite_url, audio_dir=audio_dir, port=port, log_path=log1)
    session_id = None
    try:
        _wait_until_ready(port)

        with wav_path.open("rb") as f:
            response = httpx.post(
                f"http://127.0.0.1:{port}/api/v1/sessions",
                files={"file": ("sample.wav", f, "audio/wav")},
                data={"title": "T-37 real crash", "autoProcess": "true"},
                timeout=10.0,
            )
        assert response.status_code == 201, response.text
        session_id = response.json()["sessionId"]
        assert response.json()["status"] == "TRANSCRIBING"
    finally:
        # 진짜로 전사 도중임을 보장하려고 유예 없이 즉시 죽인다 (SIGKILL, graceful shutdown 금지).
        proc1.send_signal(signal.SIGKILL)
        proc1.wait(timeout=10)

    assert session_id is not None

    engine = sa.create_engine(sqlite_url, future=True)
    with engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT status FROM sessions WHERE id = :id"), {"id": session_id}
        ).one()
    engine.dispose()
    assert row.status == "TRANSCRIBING", "강제종료 시점에 정말 처리 중이었어야 검증 의미가 있다"

    log2 = tmp_path / "server2.log"
    proc2 = _start_server(database_url=sqlite_url, audio_dir=audio_dir, port=port, log_path=log2)
    try:
        _wait_until_ready(port)

        body = httpx.get(
            f"http://127.0.0.1:{port}/api/v1/sessions/{session_id}", timeout=5.0
        ).json()
        assert body["status"] == "FAILED"
        assert body["errorCode"] == "INTERRUPTED"

        retry = httpx.post(
            f"http://127.0.0.1:{port}/api/v1/sessions/{session_id}/process", timeout=10.0
        )
        assert retry.status_code == 202, retry.text

        final_body = _wait_until_status_is(port, session_id, {"DONE", "FAILED"}, timeout=300.0)
        assert final_body["status"] == "DONE", final_body
        assert final_body["transcript"]["available"] is True
        assert final_body["summary"] is not None
    finally:
        proc2.terminate()
        proc2.wait(timeout=10)
