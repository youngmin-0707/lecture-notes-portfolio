"""POST /api/v1/sessions/{id}/summarize 테스트 (T-25, US-17, §5.3⑥).

`client`(SAVEPOINT 격리) 픽스처는 응답 계약만 검증한다 — 백그라운드 작업이 실제로 끝까지
실행되어 기존 요약을 보존한 채 새 요약을 추가하는지는 `real_client`(실커밋)로 별도 검증한다
(`tests/test_sessions_process_api.py`와 동일한 관례).
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


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status=SessionStatus.DONE.value,
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


def _add_transcript(db_session, session: Session) -> Transcript:
    transcript = Transcript(
        session_id=session.id,
        text_raw="오늘은 이진 탐색 트리에 대해 알아보겠습니다.",
        text_corrected=None,
        language="ko",
        provider="fake",
        provider_model="fake-large",
        elapsed_seconds=1.5,
    )
    db_session.add(transcript)
    db_session.flush()
    return transcript


def _add_summary(
    db_session,
    session: Session,
    *,
    content_markdown: str = "## 한 줄 요약\n요약\n\n## 핵심 주제\n없음",
) -> Summary:
    summary = Summary(
        session_id=session.id,
        content_markdown=content_markdown,
        key_points=[],
        concepts=[],
        code_snippets=[],
        action_items=[],
        keywords=[],
        provider="fake",
        provider_model="fake-model",
    )
    db_session.add(summary)
    db_session.flush()
    return summary


class TestResummarizeNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.post("/api/v1/sessions/does-not-exist/summarize")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestResummarizeRequiresTranscript:
    def test_returns_409_when_no_transcript(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.UPLOADED.value)
        db_session.add(session)
        db_session.flush()

        response = client.post(f"/api/v1/sessions/{session.id}/summarize")

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TRANSCRIPT_NOT_READY"


class TestResummarizeAcceptsAndSchedules:
    def test_done_session_returns_202_and_transitions_to_summarizing(
        self, client, db_session
    ) -> None:
        session = _make_session(status=SessionStatus.DONE.value)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)
        _add_summary(db_session, session)

        response = client.post(f"/api/v1/sessions/{session.id}/summarize")

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["sessionId"] == session.id
        assert body["status"] == "SUMMARIZING"
        assert body["pollAfterSeconds"] == 5

    def test_failed_session_with_transcript_returns_202(self, client, db_session) -> None:
        """US-17: DONE 또는 요약 단계 FAILED 상태에서 재요약할 수 있다."""
        session = _make_session(status=SessionStatus.FAILED.value, error_code="LLM_FAILED")
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.post(f"/api/v1/sessions/{session.id}/summarize")

        assert response.status_code == 202, response.text

    def test_accepts_optional_llm_provider_body(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.DONE.value)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.post(
            f"/api/v1/sessions/{session.id}/summarize", json={"llmProvider": "gemini"}
        )

        assert response.status_code == 202, response.text

    def test_no_body_at_all_is_accepted(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.DONE.value)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.post(f"/api/v1/sessions/{session.id}/summarize")

        assert response.status_code == 202, response.text


class TestResummarizeRejectsDuplicateInFlight:
    @pytest.mark.parametrize(
        "status", [SessionStatus.TRANSCRIBING.value, SessionStatus.SUMMARIZING.value]
    )
    def test_returns_409_when_already_processing(self, client, db_session, status: str) -> None:
        session = _make_session(status=status)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.post(f"/api/v1/sessions/{session.id}/summarize")

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"


class TestResummarizeEndToEndViaBackgroundTask:
    """실제 커밋 + BackgroundTasks 실행 경로로 US-17을 끝까지 검증한다."""

    def test_transcript_untouched_and_new_summary_added_and_shown_as_latest(
        self, real_client, engine
    ) -> None:
        setup_db = ORMSession(bind=engine, future=True)
        session = _make_session(status=SessionStatus.DONE.value)
        setup_db.add(session)
        setup_db.flush()
        transcript = Transcript(
            session_id=session.id,
            text_raw="원본 전사 텍스트",
            text_corrected=None,
            language="ko",
            provider="fake",
            provider_model="fake-large",
        )
        setup_db.add(transcript)
        setup_db.flush()
        old_summary = Summary(
            session_id=session.id,
            content_markdown="## 한 줄 요약\n기존 요약\n\n## 핵심 주제\n없음",
            key_points=[],
            concepts=[],
            code_snippets=[],
            action_items=[],
            keywords=[],
            provider="fake",
            provider_model="old-model",
        )
        setup_db.add(old_summary)
        setup_db.commit()
        session_id = session.id
        transcript_id = transcript.id
        setup_db.close()

        try:
            response = real_client.post(
                f"/api/v1/sessions/{session_id}/summarize",
                json={"llmProvider": "ollama"},
            )
            assert response.status_code == 202, response.text
            assert response.json()["status"] == "SUMMARIZING"

            check_db = ORMSession(bind=engine, future=True)
            persisted_session = check_db.get(Session, session_id)
            assert persisted_session.status == SessionStatus.DONE.value

            # 전사는 재실행되지 않았다 — 원본 그대로.
            persisted_transcript = check_db.get(Transcript, transcript_id)
            assert persisted_transcript is not None
            assert persisted_transcript.text_raw == "원본 전사 텍스트"

            # 기존 요약은 보존되고, 새 요약이 추가되어 총 2건이다.
            summaries = (
                check_db.execute(
                    Summary.__table__.select()
                    .where(Summary.session_id == session_id)
                    .order_by(Summary.created_at)
                )
                .mappings()
                .all()
            )
            assert len(summaries) == 2
            assert (
                summaries[0]["content_markdown"] == "## 한 줄 요약\n기존 요약\n\n## 핵심 주제\n없음"
            )
            check_db.close()

            # 조회 시 최신 요약이 기본 표시된다 (T-13 GET /sessions/{id}).
            detail = real_client.get(f"/api/v1/sessions/{session_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["summary"]["providerModel"] != "old-model"
        finally:
            cleanup_db = ORMSession(bind=engine, future=True)
            cleanup_db.execute(delete(Session).where(Session.id == session_id))
            cleanup_db.commit()
            cleanup_db.close()
