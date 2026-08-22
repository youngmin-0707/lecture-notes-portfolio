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
