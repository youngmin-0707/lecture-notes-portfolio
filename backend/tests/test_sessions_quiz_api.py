"""POST/GET /api/v1/sessions/{id}/quiz 테스트 (2026-09-01, 복습 문제 자동 생성 기능).

`app/pipeline/quiz.py`(실제 LLM 호출·상태 전이 로직)는 `tests/test_pipeline_quiz.py`가
직접 검증한다. 여기서는 라우터 레벨의 동기 부분만 다룬다 — `POST`가 트리거하는
`BackgroundTasks`는 `SessionLocal()`로 별도 커넥션을 여는데, 테스트의 `db_session`은
커밋되지 않은 SAVEPOINT 트랜잭션 안에 있어 그 커넥션에서는 보이지 않는다(`POST /sessions`
autoProcess 테스트와 동일한 기존 관례, `tests/test_sessions_create_api.py` 참고) — 그래서
"생성 완료"까지는 이 파일에서 검증하지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.enums import QuizStatus, SessionStatus
from app.models.quiz import Quiz
from app.models.session import Session
from app.models.summary import Summary


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status=SessionStatus.DONE.value,
        source="UPLOAD",
        audio_path=None,
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=3600.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


def _add_summary(db_session, session: Session, *, detailed_notes: str = "1. BST\n정의.") -> Summary:
    summary = Summary(
        session_id=session.id,
        content_markdown="## 한 줄 요약\n이진 탐색 트리 강의입니다.",
        key_points=[],
        keywords=[],
        detailed_notes_markdown=detailed_notes,
        provider="fake",
        provider_model="fake-large",
    )
    db_session.add(summary)
    db_session.flush()
    return summary


def _add_quiz(db_session, session: Session, **overrides) -> Quiz:
    defaults = dict(
        session_id=session.id,
        status=QuizStatus.DONE.value,
        questions=[{"question": "왜 BST를 쓰나요?", "answer": "탐색이 O(log n)이기 때문입니다."}],
        provider="fake",
        provider_model="fake-large",
    )
    defaults.update(overrides)
    quiz = Quiz(**defaults)
    db_session.add(quiz)
    db_session.flush()
    return quiz


class TestCreateQuizNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.post("/api/v1/sessions/does-not-exist/quiz")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestCreateQuizSummaryNotReady:
    def test_returns_409_when_no_summary_exists(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.post(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SUMMARY_NOT_READY"

    def test_returns_409_when_summary_has_empty_detailed_notes(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session, detailed_notes="")

        response = client.post(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SUMMARY_NOT_READY"


class TestCreateQuizAccepted:
    def test_returns_202_generating_and_persists_row(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.post(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 202
        body = response.json()
        assert body["sessionId"] == session.id
        assert body["status"] == "GENERATING"
        assert body["pollAfterSeconds"] > 0

    def test_returns_409_when_already_generating(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        _add_quiz(db_session, session, status=QuizStatus.GENERATING.value, questions=[])

        response = client.post(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"

    def test_allows_regeneration_after_done(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        _add_quiz(db_session, session, status=QuizStatus.DONE.value)

        response = client.post(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 202
        assert response.json()["status"] == "GENERATING"

    def test_allows_retry_after_failed(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        _add_quiz(
            db_session,
            session,
            status=QuizStatus.FAILED.value,
            questions=[],
            error_code="LLM_FAILED",
            error_message="실패",
        )

        response = client.post(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 202
        assert response.json()["status"] == "GENERATING"


class TestGetQuizNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.get("/api/v1/sessions/does-not-exist/quiz")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_returns_404_when_never_generated(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "QUIZ_NOT_FOUND"


class TestGetQuizExisting:
    def test_returns_latest_done_quiz_with_questions(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_quiz(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "DONE"
        assert body["pollAfterSeconds"] is None
        assert len(body["questions"]) == 1
        assert body["questions"][0]["question"] == "왜 BST를 쓰나요?"
        assert body["questions"][0]["answer"]

    def test_returns_generating_with_poll_hint(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_quiz(db_session, session, status=QuizStatus.GENERATING.value, questions=[])

        response = client.get(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "GENERATING"
        assert body["pollAfterSeconds"] > 0

    def test_returns_failed_with_error_info(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_quiz(
            db_session,
            session,
            status=QuizStatus.FAILED.value,
            questions=[],
            error_code="LLM_INVALID_RESPONSE",
            error_message="요약 결과 형식이 올바르지 않습니다.",
        )

        response = client.get(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["errorCode"] == "LLM_INVALID_RESPONSE"

    def test_returns_most_recently_created_when_multiple_exist(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_quiz(
            db_session,
            session,
            questions=[{"question": "예전 문제", "answer": "예전 답"}],
            created_at=datetime(2026, 8, 30, tzinfo=UTC),
        )
        _add_quiz(
            db_session,
            session,
            questions=[{"question": "최신 문제", "answer": "최신 답"}],
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

        response = client.get(f"/api/v1/sessions/{session.id}/quiz")

        assert response.status_code == 200
        assert response.json()["questions"][0]["question"] == "최신 문제"
