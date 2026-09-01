"""PATCH /api/v1/sessions/{id} 테스트 (§5.2 ⑪, P2, T-34 프론트 메타데이터 편집 선행 작업).

§5.3에 상세 스펙이 없어 기존 관례(부분 업데이트, GET과 동일한 응답 구조)를 따른다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.models.session import Session


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status="DONE",
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


class TestUpdateSessionNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.patch("/api/v1/sessions/does-not-exist", json={"title": "새 제목"})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestUpdateSessionPartial:
    def test_updates_title_only(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"title": "새 제목"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "새 제목"
        assert body["course"] == "자료구조"

    def test_updates_course_only(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"course": "새 과목"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "자료구조 7주차"
        assert body["course"] == "새 과목"

    def test_updates_both(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(
            f"/api/v1/sessions/{session.id}",
            json={"title": "새 제목", "course": "새 과목"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "새 제목"
        assert body["course"] == "새 과목"

    def test_empty_body_leaves_fields_unchanged(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == "자료구조 7주차"
        assert body["course"] == "자료구조"

    def test_response_shape_matches_get_detail(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"title": "새 제목"})

        body = response.json()
        assert "transcript" in body
        assert "summary" in body
        assert body["status"] == "DONE"

    def test_allowed_while_processing(self, client, db_session) -> None:
        """메타데이터 수정은 파이프라인과 무관하므로 처리 중에도 허용한다."""
        session = _make_session(status="TRANSCRIBING")
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"title": "새 제목"})

        assert response.status_code == 200, response.text


class TestTitleCustomizedFlag:
    """2026-08-30: 제목을 직접 바꾸면 이후 요약 완료 시 자동 제목이 덮어쓰지 않는다."""

    def test_patching_title_marks_customized(self, client, db_session) -> None:
        session = _make_session(title_customized=False)
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"title": "새 제목"})

        assert response.status_code == 200, response.text
        db_session.refresh(session)
        assert session.title_customized is True

    def test_patching_only_course_does_not_mark_customized(self, client, db_session) -> None:
        session = _make_session(title_customized=False)
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"course": "새 과목"})

        assert response.status_code == 200, response.text
        db_session.refresh(session)
        assert session.title_customized is False


class TestUpdateSessionValidation:
    def test_empty_title_returns_400(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"title": ""})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_title_too_long_returns_400(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"title": "가" * 201})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_course_too_long_returns_400(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(f"/api/v1/sessions/{session.id}", json={"course": "가" * 101})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
