"""PATCH /api/v1/sessions/{id}/summary 테스트 (2026-09-14).

요약 결과가 마음에 들지 않을 때 재요약(LLM 재호출) 없이 직접 고치는 기능. `content_markdown`
재조립이 핵심이므로, 실제 `render_markdown()`이 만드는 형태와 동일한 고정 픽스처를 쓴다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.llm.parsing import render_markdown
from app.llm.schema import ParsedSummary, SummaryKeyPoint
from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.summary import Summary


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


_ORIGINAL_KEY_POINTS = [
    SummaryKeyPoint(text="이진 탐색 트리의 탐색", at_seconds=12.0),
    SummaryKeyPoint(text="삽입과 삭제", at_seconds=48.0),
]
_ORIGINAL_ONE_LINE = "이진 탐색 트리의 탐색/삽입/삭제를 다뤘다."
_ORIGINAL_DETAILED_NOTES = "## 1. 탐색\n루트에서 시작해 값을 비교하며 내려간다."


def _add_summary(db_session, session: Session, **overrides) -> Summary:
    parsed = ParsedSummary(
        one_line_summary=_ORIGINAL_ONE_LINE,
        key_points=_ORIGINAL_KEY_POINTS,
        keywords=[],
        detailed_notes=_ORIGINAL_DETAILED_NOTES,
    )
    defaults = dict(
        session_id=session.id,
        content_markdown=render_markdown(parsed),
        key_points=[{"text": p.text, "atSeconds": p.at_seconds} for p in _ORIGINAL_KEY_POINTS],
        concepts=[],
        code_snippets=[],
        action_items=[],
        keywords=[],
        detailed_notes_markdown=_ORIGINAL_DETAILED_NOTES,
        provider="fake",
        provider_model="fake-model",
    )
    defaults.update(overrides)
    summary = Summary(**defaults)
    db_session.add(summary)
    db_session.flush()
    return summary


class TestUpdateSummaryNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.patch(
            "/api/v1/sessions/does-not-exist/summary",
            json={"detailedNotesMarkdown": "새 내용"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestUpdateSummaryNotReady:
    def test_returns_409_when_no_summary_exists_yet(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": "새 내용"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SUMMARY_NOT_READY"


class TestUpdateSummaryBlockedWhileProcessing:
    def test_returns_409_while_summarizing(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.SUMMARIZING.value)
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": "새 내용"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"

    def test_returns_409_while_transcribing(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBING.value)
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": "새 내용"},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_SESSION_STATE"


class TestUpdateDetailedNotesOnly:
    def test_updates_body_and_keeps_one_line_summary(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        new_notes = "## 1. 고친 내용\n삭제는 세 가지 경우로 나뉜다."
        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": new_notes},
        )

        assert response.status_code == 200, response.text
        summary = response.json()["summary"]
        assert summary["detailedNotesMarkdown"] == new_notes
        assert new_notes in summary["contentMarkdown"]
        # 한 줄 요약은 건드리지 않았으니 그대로 남아야 한다.
        assert _ORIGINAL_ONE_LINE in summary["contentMarkdown"]
        assert _ORIGINAL_DETAILED_NOTES not in summary["contentMarkdown"]

    def test_key_points_are_preserved(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": "새 본문"},
        )

        assert response.status_code == 200, response.text
        key_points = response.json()["summary"]["keyPoints"]
        assert len(key_points) == 2
        assert key_points[0]["text"] == "이진 탐색 트리의 탐색"
        assert key_points[0]["atSeconds"] == 12.0


class TestUpdateOneLineSummaryOnly:
    def test_updates_one_line_summary_and_keeps_body(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        new_one_line = "요점만 다시 정리한 한 줄 요약."
        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"oneLineSummary": new_one_line},
        )

        assert response.status_code == 200, response.text
        summary = response.json()["summary"]
        assert new_one_line in summary["contentMarkdown"]
        assert _ORIGINAL_ONE_LINE not in summary["contentMarkdown"]
        # 본문은 손대지 않았으니 그대로 유지되어야 한다.
        assert summary["detailedNotesMarkdown"] == _ORIGINAL_DETAILED_NOTES


class TestUpdateBothFields:
    def test_updates_both(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"oneLineSummary": "새 한 줄 요약", "detailedNotesMarkdown": "새 본문"},
        )

        assert response.status_code == 200, response.text
        summary = response.json()["summary"]
        assert "새 한 줄 요약" in summary["contentMarkdown"]
        assert summary["detailedNotesMarkdown"] == "새 본문"


class TestUpdateSummaryEmptyBodyIsNoop:
    def test_empty_body_leaves_content_effectively_unchanged(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(f"/api/v1/sessions/{session.id}/summary", json={})

        assert response.status_code == 200, response.text
        summary = response.json()["summary"]
        assert summary["detailedNotesMarkdown"] == _ORIGINAL_DETAILED_NOTES
        assert _ORIGINAL_ONE_LINE in summary["contentMarkdown"]


class TestUpdateSummaryValidation:
    def test_empty_detailed_notes_returns_400(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": ""},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_empty_one_line_summary_returns_400(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)

        response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"oneLineSummary": ""},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestUpdateSummaryReflectedInExport:
    def test_markdown_export_reflects_edited_content(self, client, db_session) -> None:
        from app.models.transcript import Transcript

        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(db_session, session)
        db_session.add(
            Transcript(
                session_id=session.id,
                text_raw="원문 전사",
                language="ko",
                provider="fake",
                provider_model="fake-model",
            )
        )
        db_session.flush()

        edit_response = client.patch(
            f"/api/v1/sessions/{session.id}/summary",
            json={"detailedNotesMarkdown": "수정된 본문 내용"},
        )
        assert edit_response.status_code == 200, edit_response.text

        export_response = client.get(f"/api/v1/sessions/{session.id}/export?format=md")
        assert export_response.status_code == 200, export_response.text
        assert "수정된 본문 내용" in export_response.text
