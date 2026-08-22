"""복구 스윕 테스트 (T-20, §3.6, US-10).

`sweep_interrupted_sessions()` 단위 테스트와, 서버 재기동을 흉내낸 lifespan 통합 테스트
둘 다 포함한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session as ORMSession

from app.main import app
from app.models.enums import SessionStatus
from app.models.session import Session
from app.pipeline.recovery import sweep_interrupted_sessions


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


class TestSweepInterruptedSessionsUnit:
    def test_transcribing_session_marked_interrupted(self, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBING.value)
        db_session.add(session)
        db_session.flush()

        swept_ids = sweep_interrupted_sessions(db_session)

        assert session.id in swept_ids
        assert session.status == SessionStatus.FAILED.value
        assert session.error_code == "INTERRUPTED"
        assert session.error_message

    def test_summarizing_session_marked_interrupted(self, db_session) -> None:
        session = _make_session(status=SessionStatus.SUMMARIZING.value)
        db_session.add(session)
        db_session.flush()

        swept_ids = sweep_interrupted_sessions(db_session)

        assert session.id in swept_ids
        assert session.status == SessionStatus.FAILED.value
        assert session.error_code == "INTERRUPTED"

    def test_non_processing_statuses_are_untouched(self, db_session) -> None:
        untouched_statuses = [
            SessionStatus.UPLOADED.value,
            SessionStatus.TRANSCRIBED.value,
            SessionStatus.DONE.value,
            SessionStatus.FAILED.value,
        ]
        sessions = [_make_session(status=status) for status in untouched_statuses]
        for session in sessions:
            db_session.add(session)
        db_session.flush()

        swept_ids = sweep_interrupted_sessions(db_session)

        assert swept_ids == []
        for session in sessions:
            assert session.status in untouched_statuses

    def test_returns_empty_list_when_nothing_to_sweep(self, db_session) -> None:
        assert sweep_interrupted_sessions(db_session) == []


class TestRecoverySweepOnServerStartup:
    """US-10: TRANSCRIBING 상태 세션이 있는 상태로 서버가 재기동되면 FAILED(INTERRUPTED)로
    전이되고, 이후 사용자가 재실행할 수 있는 상태가 된다."""

    def test_transcribing_session_interrupted_on_startup(self, engine) -> None:
        setup_db = ORMSession(bind=engine, future=True)
        session = _make_session(status=SessionStatus.TRANSCRIBING.value)
        setup_db.add(session)
        setup_db.commit()
        session_id = session.id
        setup_db.close()

        try:
            # 새 TestClient 컨텍스트 진입 = 서버 재기동을 흉내낸다. lifespan startup에서
            # 복구 스윕이 실행되어야 한다.
            with TestClient(app) as fresh_client:
                response = fresh_client.get(f"/api/v1/sessions/{session_id}")
                assert response.status_code == 200
                body = response.json()
                assert body["status"] == "FAILED"
                assert body["errorCode"] == "INTERRUPTED"
        finally:
            cleanup_db = ORMSession(bind=engine, future=True)
            cleanup_db.execute(delete(Session).where(Session.id == session_id))
            cleanup_db.commit()
            cleanup_db.close()
