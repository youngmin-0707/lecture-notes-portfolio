"""POST /api/v1/sessions/{id}/process 테스트 (T-19, US-02).

`client`(SAVEPOINT 격리) 픽스처는 응답 계약(status code/body)을 검증한다 — 백그라운드
작업은 별도 DB 커넥션을 쓰므로 아직 커밋되지 않은 세션을 보지 못해 조용히 no-op된다
(별도 커넥션이 격리된 트랜잭션을 보지 못하는 것은 의도된 정상 동작이다).

실제로 백그라운드 작업이 끝까지 실행되어 DONE에 도달하는지는 `real_client`(실커밋) +
Fake Provider로 별도 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session as ORMSession

from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.pipeline import progress as progress_module


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status=SessionStatus.UPLOADED.value,
        source="UPLOAD",
        audio_path="data/audio/dummy.upload",
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=120.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


@pytest.fixture(autouse=True)
def _clear_progress_store():
    progress_module.clear_all_progress()
    yield
    progress_module.clear_all_progress()


class TestProcessNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.post("/api/v1/sessions/does-not-exist/process")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestProcessAcceptsAndSchedules:
    def test_uploaded_session_returns_202_and_transitions_to_transcribing(
        self, client, db_session
    ) -> None:
        session = _make_session(status=SessionStatus.UPLOADED.value)
        db_session.add(session)
        db_session.flush()

        response = client.post(f"/api/v1/sessions/{session.id}/process")

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["sessionId"] == session.id
        assert body["status"] == "TRANSCRIBING"
        assert body["pollAfterSeconds"] > 0

    def test_accepts_optional_request_body(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.UPLOADED.value)
        db_session.add(session)
        db_session.flush()

        response = client.post(
            f"/api/v1/sessions/{session.id}/process",
            json={"sttModel": "large-v3-turbo", "llmProvider": "ollama", "skipSummary": True},
        )

        assert response.status_code == 202, response.text

    def test_no_body_at_all_is_accepted(self, client, db_session) -> None:
        """§5.3②: Request Body는 전부 선택이므로 바디 없이 호출해도 202여야 한다."""
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()

        response = client.post(f"/api/v1/sessions/{session.id}/process")

        assert response.status_code == 202, response.text


class TestProcessEndToEndViaBackgroundTask:
    """실제 커밋 + BackgroundTasks 실행 경로 전체를 검증한다 (T-19 핵심 배관).

    `conftest._fake_pipeline_providers`(autouse)가 이미 STT/LLM을 Fake로 바꿔두므로 실제
    Whisper/Ollama는 전혀 관여하지 않는다 — 여기서 검증하는 건 "202 응답 → 별도 DB 세션에서
    백그라운드 작업 실행 → 실제로 DONE까지 도달"이라는 배관 자체다.
    """

    def test_background_task_runs_to_done(self, real_client, engine) -> None:
        setup_db = ORMSession(bind=engine, future=True)
        session = _make_session(status=SessionStatus.UPLOADED.value)
        setup_db.add(session)
        setup_db.commit()
        session_id = session.id
        setup_db.close()

        try:
            response = real_client.post(f"/api/v1/sessions/{session_id}/process")
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "TRANSCRIBING"

            # TestClient는 백그라운드 작업을 응답 반환 직후 동기적으로 실행하므로, 이 시점에는
            # 이미 완료되어 있어야 한다.
            check_db = ORMSession(bind=engine, future=True)
            persisted = check_db.get(Session, session_id)
            assert persisted.status == SessionStatus.DONE.value
            transcript_row = check_db.execute(
                Transcript.__table__.select().where(Transcript.session_id == session_id)
            ).first()
            assert transcript_row is not None
            summary_row = check_db.execute(
                Summary.__table__.select().where(Summary.session_id == session_id)
            ).first()
            assert summary_row is not None
            check_db.close()
        finally:
            cleanup_db = ORMSession(bind=engine, future=True)
            cleanup_db.execute(delete(Session).where(Session.id == session_id))
            cleanup_db.commit()
            cleanup_db.close()


class TestProcessRejectsDuplicateInFlight:
    @pytest.mark.parametrize(
        "status",
        [SessionStatus.TRANSCRIBING.value, SessionStatus.SUMMARIZING.value],
    )
    def test_returns_409_when_already_processing(self, client, db_session, status: str) -> None:
        session = _make_session(status=status)
        db_session.add(session)
        db_session.flush()

        response = client.post(f"/api/v1/sessions/{session.id}/process")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"

    @pytest.mark.parametrize(
        "status",
        [
            SessionStatus.UPLOADED.value,
            SessionStatus.TRANSCRIBED.value,
            SessionStatus.DONE.value,
            SessionStatus.FAILED.value,
        ],
    )
    def test_allows_reprocessing_from_other_statuses(self, client, db_session, status: str) -> None:
        session = _make_session(status=status)
        db_session.add(session)
        db_session.flush()

        response = client.post(f"/api/v1/sessions/{session.id}/process")

        assert response.status_code == 202, response.text
