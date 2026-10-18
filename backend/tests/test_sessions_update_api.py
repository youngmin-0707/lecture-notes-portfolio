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


class TestUpdateRecordedAt:
    """2026-10-07: 세션을 다른 일자로 옮긴다 — 업로드일과 실제 수업일이 다를 때 바로잡는 용도."""

    def test_updates_recorded_at(self, client, db_session) -> None:
        session = _make_session(recorded_at=datetime(2026, 10, 7, 1, 25, 5, tzinfo=UTC))
        db_session.add(session)
        db_session.flush()

        response = client.patch(
            f"/api/v1/sessions/{session.id}", json={"recordedAt": "2026-10-01T01:25:05Z"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["recordedAt"] == "2026-10-01T01:25:05Z"

    def test_offset_datetime_is_normalized_to_utc(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(
            f"/api/v1/sessions/{session.id}", json={"recordedAt": "2026-10-01T08:00:00+09:00"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["recordedAt"] == "2026-09-30T23:00:00Z"

    def test_moved_session_is_found_by_new_date_filter(self, client, db_session) -> None:
        session = _make_session(recorded_at=datetime(2026, 10, 7, 1, 25, 5, tzinfo=UTC))
        db_session.add(session)
        db_session.flush()

        client.patch(f"/api/v1/sessions/{session.id}", json={"recordedAt": "2026-10-01T01:25:05Z"})

        moved = client.get(
            "/api/v1/sessions", params={"date_from": "2026-10-01", "date_to": "2026-10-01"}
        ).json()["items"]
        assert [item["sessionId"] for item in moved] == [session.id]

    def test_does_not_touch_title_or_customized_flag(self, client, db_session) -> None:
        session = _make_session(title_customized=False)
        db_session.add(session)
        db_session.flush()

        response = client.patch(
            f"/api/v1/sessions/{session.id}", json={"recordedAt": "2026-10-01T01:25:05Z"}
        )

        assert response.json()["title"] == "자료구조 7주차"
        db_session.refresh(session)
        assert session.title_customized is False

    def test_datetime_without_timezone_returns_400(self, client, db_session) -> None:
        """시간대가 없으면 어느 날짜인지 확정할 수 없다 — 조용히 UTC로 간주하지 않는다."""
        session = _make_session()
        db_session.add(session)
        db_session.flush()

        response = client.patch(
            f"/api/v1/sessions/{session.id}", json={"recordedAt": "2026-10-01T08:00:00"}
        )

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
