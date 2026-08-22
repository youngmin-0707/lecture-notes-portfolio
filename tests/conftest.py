"""pytest 공통 픽스처.

전제:
- `app.main` 모듈에 FastAPI 인스턴스 `app` 이 존재한다.
- `app.db.base` 모듈에 SQLAlchemy 선언적 Base `Base` 가 존재한다.
- `app.db.session` 모듈에 FastAPI 의존성 `get_db` (Session을 yield하는 제너레이터)가 존재한다.
- `app.models` 패키지를 import하면 모든 ORM 모델이 `Base.metadata`에 등록된다
  (즉, `app/models/__init__.py`에서 각 모델 모듈을 import 해야 한다).

테스트 DB:
- 환경변수 `TEST_DATABASE_URL` 로 지정 (기본값: 아래 DEFAULT_TEST_DATABASE_URL).
- `backend/docker-compose.test.yml` 로 로컬 PostgreSQL 테스트 DB를 띄울 수 있다.
- 각 테스트는 트랜잭션(SAVEPOINT)으로 감싸여 테스트 종료 시 자동 롤백되어 격리된다
  (SQLAlchemy 2.0 `join_transaction_mode="create_savepoint"` 패턴).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5433/app_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)

# app을 import 하기 전에, app이 참조할 환경변수를 먼저 세팅한다.
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("ENVIRONMENT", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import models  # noqa: E402,F401  # 모든 모델을 Base.metadata에 등록시키기 위한 import
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(TEST_DATABASE_URL, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Iterator[Session]:
    """테스트 1건을 SAVEPOINT로 감싸고, 종료 시 롤백해 DB 상태를 격리한다."""
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """DB 의존성을 격리된 세션으로 오버라이드한 일반 테스트 클라이언트."""

    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def real_client(engine: Engine) -> Iterator[TestClient]:
    """DB 의존성을 오버라이드하지 않는 클라이언트. 실제 커밋이 필요한 테스트 전용."""
    app.dependency_overrides.pop(get_db, None)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 오디오 픽스처 (T-05, §3.1 업로드 검증 / US-01·US-06·US-07)
#
# 실제 인코더(ffmpeg 등) 의존 없이 파이썬 표준 라이브러리 `wave` 모듈만으로 디코딩
# 가능한 최소 WAV를 생성한다. "위장 파일"은 실제로는 오디오가 아닌 콘텐츠에 오디오
# 확장자를 붙인 것이고, "손상 파일"은 컨테이너 헤더는 있지만 디코딩이 불가능한 것이다.
# 대용량(500MB급) 파일은 디스크/메모리 낭비를 피하기 위해 필요한 테스트에서
# `make_wav_bytes`로 그때그때 런타임에 생성한다 (미리 저장해두지 않는다).
# ---------------------------------------------------------------------------


def _build_wav_bytes(duration_seconds: float, *, sample_rate: int = 16000) -> bytes:
    """지정한 길이의 무음 PCM WAV를 바이트로 생성한다 (실제 디코딩 가능한 오디오)."""
    import io
    import wave

    n_frames = max(int(duration_seconds * sample_rate), 0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


@pytest.fixture()
def make_wav_bytes():
    """`(duration_seconds) -> bytes` 팩토리. 임의 길이의 유효한 WAV를 생성한다."""
    return _build_wav_bytes


@pytest.fixture()
def valid_wav_bytes() -> bytes:
    """2초짜리 정상 WAV (디코딩 가능, 최소 길이 요건을 만족)."""
    return _build_wav_bytes(2.0)


@pytest.fixture()
def too_short_wav_bytes() -> bytes:
    """0.5초짜리 WAV — §3.1 `AUDIO_TOO_SHORT`(1초 이하) 검증용."""
    return _build_wav_bytes(0.5)


@pytest.fixture()
def disguised_pdf_as_mp3_bytes() -> bytes:
    """PDF 매직 넘버(`%PDF-`)를 가진, 확장자만 mp3로 위장한 파일 (US-07)."""
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + (b"not audio content " * 50)


@pytest.fixture()
def corrupted_wav_bytes() -> bytes:
    """WAV 매직 넘버(`RIFF...WAVE`)는 있지만 나머지가 깨져 디코딩이 불가능한 파일."""
    return b"RIFF" + (24).to_bytes(4, "little") + b"WAVE" + b"\x00" * 40


@pytest.fixture()
def not_audio_bytes() -> bytes:
    """매직 넘버 자체가 알려진 오디오 형식이 아닌 임의 바이너리 (US-06)."""
    return b"this is just plain text pretending to be audio\n" * 20
