"""GET /api/v1/sessions + DELETE /api/v1/sessions/{id} 테스트 (T-24, US-14, US-18)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
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


def _add_summary(db_session, session: Session, *, content_markdown: str) -> Summary:
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


class TestListSessions:
    def test_empty_returns_empty_items(self, client) -> None:
        response = client.get("/api/v1/sessions")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {"items": [], "page": 1, "size": 20, "totalCount": 0, "totalPages": 0}

    def test_returns_sorted_by_recorded_at_desc(self, client, db_session) -> None:
        now = datetime.now(UTC)
        older = _make_session(title="1주차", recorded_at=now - timedelta(days=7))
        newer = _make_session(title="2주차", recorded_at=now)
        db_session.add_all([older, newer])
        db_session.flush()

        response = client.get("/api/v1/sessions")

        assert response.status_code == 200, response.text
        titles = [item["title"] for item in response.json()["items"]]
        assert titles == ["2주차", "1주차"]

    def test_items_include_required_fields_and_exclude_full_text(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(
            db_session,
            session,
            content_markdown=(
                "## 한 줄 요약\n이진 탐색 트리의 구조와 순회 방식을 다룸.\n\n## 핵심 주제\n없음"
            ),
        )

        response = client.get("/api/v1/sessions")

        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["sessionId"] == session.id
        assert item["title"] == "자료구조 7주차"
        assert item["course"] == "자료구조"
        assert item["status"] == "DONE"
        assert item["durationSeconds"] == 120.0
        assert item["summaryPreview"] == "이진 탐색 트리의 구조와 순회 방식을 다룸."
        assert "text" not in item
        assert "transcript" not in item
        assert "contentMarkdown" not in item

    def test_summary_preview_null_when_no_summary_yet(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()

        response = client.get("/api/v1/sessions")

        assert response.json()["items"][0]["summaryPreview"] is None

    def test_summary_preview_truncated_to_200_chars(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        long_text = "가" * 500
        _add_summary(
            db_session,
            session,
            content_markdown=f"## 한 줄 요약\n{long_text}\n\n## 핵심 주제\n없음",
        )

        response = client.get("/api/v1/sessions")

        preview = response.json()["items"][0]["summaryPreview"]
        assert len(preview) == 200

    def test_summary_preview_uses_latest_summary(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(
            db_session,
            session,
            content_markdown="## 한 줄 요약\n첫 번째 요약\n\n## 핵심 주제\n없음",
        )
        _add_summary(
            db_session,
            session,
            content_markdown="## 한 줄 요약\n두 번째(최신) 요약\n\n## 핵심 주제\n없음",
        )

        response = client.get("/api/v1/sessions")

        assert response.json()["items"][0]["summaryPreview"] == "두 번째(최신) 요약"

    def test_filters_by_course(self, client, db_session) -> None:
        db_session.add_all(
            [
                _make_session(title="자료구조", course="자료구조"),
                _make_session(title="네트워크", course="네트워크"),
            ]
        )
        db_session.flush()

        response = client.get("/api/v1/sessions", params={"course": "네트워크"})

        titles = [item["title"] for item in response.json()["items"]]
        assert titles == ["네트워크"]

    def test_filters_by_status(self, client, db_session) -> None:
        db_session.add_all(
            [
                _make_session(title="완료", status=SessionStatus.DONE.value),
                _make_session(title="실패", status=SessionStatus.FAILED.value),
            ]
        )
        db_session.flush()

        response = client.get("/api/v1/sessions", params={"status": "FAILED"})

        titles = [item["title"] for item in response.json()["items"]]
        assert titles == ["실패"]

    def test_filters_by_title_query(self, client, db_session) -> None:
        db_session.add_all(
            [
                _make_session(title="RAG와 PGVector 실습"),
                _make_session(title="이진 탐색 트리"),
            ]
        )
        db_session.flush()

        response = client.get("/api/v1/sessions", params={"q": "pgvector"})

        titles = [item["title"] for item in response.json()["items"]]
        assert titles == ["RAG와 PGVector 실습"]

    def test_filters_by_summary_content_query(self, client, db_session) -> None:
        with_match = _make_session(title="9주차")
        without_match = _make_session(title="10주차")
        db_session.add_all([with_match, without_match])
        db_session.flush()
        _add_summary(db_session, with_match, content_markdown="## 한 줄 요약\n임베딩과 벡터 검색")
        _add_summary(db_session, without_match, content_markdown="## 한 줄 요약\n재귀와 반복문")

        response = client.get("/api/v1/sessions", params={"q": "임베딩"})

        titles = [item["title"] for item in response.json()["items"]]
        assert titles == ["9주차"]

    def test_query_only_matches_latest_summary(self, client, db_session) -> None:
        """세션당 여러 요약이 있을 때(재요약), 최신 요약 내용만 검색 대상이어야 한다."""
        session = _make_session(title="9주차")
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session, content_markdown="## 한 줄 요약\n예전 내용: 그래프")
        db_session.flush()
        _add_summary(db_session, session, content_markdown="## 한 줄 요약\n최신 내용: 트리")

        old_match = client.get("/api/v1/sessions", params={"q": "그래프"})
        new_match = client.get("/api/v1/sessions", params={"q": "트리"})

        assert old_match.json()["items"] == []
        assert [item["title"] for item in new_match.json()["items"]] == ["9주차"]

    def test_filters_by_date_range(self, client, db_session) -> None:
        db_session.add_all(
            [
                _make_session(title="8월25일", recorded_at=datetime(2026, 8, 25, tzinfo=UTC)),
                _make_session(title="8월30일", recorded_at=datetime(2026, 8, 30, tzinfo=UTC)),
                _make_session(title="9월1일", recorded_at=datetime(2026, 9, 1, tzinfo=UTC)),
            ]
        )
        db_session.flush()

        response = client.get(
            "/api/v1/sessions", params={"date_from": "2026-08-26", "date_to": "2026-08-31"}
        )

        titles = [item["title"] for item in response.json()["items"]]
        assert titles == ["8월30일"]

    def test_invalid_status_returns_400(self, client) -> None:
        response = client.get("/api/v1/sessions", params={"status": "NOT_A_STATUS"})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_page_less_than_1_returns_400(self, client) -> None:
        response = client.get("/api/v1/sessions", params={"page": 0})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_size_over_100_returns_400(self, client) -> None:
        response = client.get("/api/v1/sessions", params={"size": 101})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_pagination_page_and_size_and_total_pages(self, client, db_session) -> None:
        now = datetime.now(UTC)
        db_session.add_all(
            [
                _make_session(title=f"세션{i}", recorded_at=now - timedelta(minutes=i))
                for i in range(5)
            ]
        )
        db_session.flush()

        response = client.get("/api/v1/sessions", params={"page": 2, "size": 2})

        body = response.json()
        assert body["page"] == 2
        assert body["size"] == 2
        assert body["totalCount"] == 5
        assert body["totalPages"] == 3
        assert len(body["items"]) == 2
        # 최신순 정렬 기준 3~4번째 항목(0-indexed로 세션2, 세션3)이어야 한다.
        assert [item["title"] for item in body["items"]] == ["세션2", "세션3"]


class TestDeleteSession:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.delete("/api/v1/sessions/does-not-exist")

        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.parametrize(
        "status", [SessionStatus.TRANSCRIBING.value, SessionStatus.SUMMARIZING.value]
    )
    def test_processing_session_returns_409(self, client, db_session, status: str) -> None:
        session = _make_session(status=status)
        db_session.add(session)
        db_session.flush()

        response = client.delete(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"

    def test_deletes_session_and_subsequent_get_is_404(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        session_id = session.id

        response = client.delete(f"/api/v1/sessions/{session_id}")

        assert response.status_code == 204, response.text
        assert response.content == b""

        follow_up = client.get(f"/api/v1/sessions/{session_id}")
        assert follow_up.status_code == 404
        assert follow_up.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_deletes_audio_file_from_disk(
        self, client, db_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        storage_dir = tmp_path / "audio"
        storage_dir.mkdir()
        monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(storage_dir))
        audio_file = storage_dir / "abc123.upload"
        audio_file.write_bytes(b"fake audio bytes")

        session = _make_session(audio_path=str(audio_file))
        db_session.add(session)
        db_session.flush()

        response = client.delete(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 204, response.text
        assert not audio_file.exists()

    def test_deleting_session_cascades_transcript_and_summary(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        transcript = Transcript(
            session_id=session.id,
            text_raw="원문",
            text_corrected=None,
            language="ko",
            provider="fake",
            provider_model="fake-large",
        )
        db_session.add(transcript)
        db_session.flush()
        _add_summary(
            db_session, session, content_markdown="## 한 줄 요약\n요약\n\n## 핵심 주제\n없음"
        )
        transcript_id = transcript.id

        response = client.delete(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 204, response.text
        # `.get()`은 아직 세션 아이덴티티맵에 남아있는(now-stale) 객체를 DB 재조회 없이
        # 그대로 반환할 수 있다 — DB의 ON DELETE CASCADE로 지워졌는지는 실제 쿼리로 확인한다.
        assert (
            db_session.execute(select(Transcript).where(Transcript.id == transcript_id)).first()
            is None
        )
        assert (
            db_session.execute(select(Summary).where(Summary.session_id == session.id)).first()
            is None
        )
