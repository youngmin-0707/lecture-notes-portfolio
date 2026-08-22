"""GET /api/v1/sessions/{id}/export 테스트 (T-27, US-16, §5.3⑦)."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import unquote

from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript, TranscriptSegment


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="7주차",
        course="자료구조",
        status="DONE",
        source="UPLOAD",
        audio_path="data/audio/dummy.upload",
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=120.0,
        recorded_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


def _add_transcript_with_segments(db_session, session: Session) -> Transcript:
    transcript = Transcript(
        session_id=session.id,
        text_raw="오늘은 이진 탐색 트리에 대해 알아보겠습니다.",
        text_corrected="오늘은 이진 탐색 트리(BST)에 대해 알아보겠습니다.",
        language="ko",
        provider="fake",
        provider_model="fake-large",
    )
    db_session.add(transcript)
    db_session.flush()
    db_session.add_all(
        [
            TranscriptSegment(
                transcript_id=transcript.id,
                seq=0,
                start_seconds=0.0,
                end_seconds=5.2,
                text="오늘은 이진 탐색 트리에 대해 알아보겠습니다.",
            ),
            TranscriptSegment(
                transcript_id=transcript.id,
                seq=1,
                start_seconds=5.2,
                end_seconds=11.8,
                text="먼저 삽입 연산부터 보겠습니다.",
            ),
        ]
    )
    db_session.flush()
    return transcript


def _add_summary(db_session, session: Session) -> Summary:
    summary = Summary(
        session_id=session.id,
        content_markdown="## 한 줄 요약\n이진 탐색 트리 강의\n\n## 핵심 주제\n없음",
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


class TestExportNotFound:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.get("/api/v1/sessions/does-not-exist/export")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestExportRequiresTranscript:
    def test_returns_409_when_no_transcript(self, client, db_session) -> None:
        session = _make_session(status="UPLOADED")
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}/export")

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TRANSCRIPT_NOT_READY"


class TestExportInvalidFormat:
    def test_unknown_format_returns_400(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/export", params={"format": "pdf"})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestExportMarkdown:
    def test_default_format_is_markdown(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session)
        _add_summary(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/export")

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        assert "# 7주차" in response.text
        assert "이진 탐색 트리 강의" in response.text
        assert "## 전사 전문" in response.text

    def test_content_disposition_filename(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/export", params={"format": "md"})

        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        encoded = disposition.split("filename*=UTF-8''", 1)[1]
        assert unquote(encoded) == "2026-08-20_자료구조_7주차.md"

    def test_missing_summary_still_exports_transcript(self, client, db_session) -> None:
        session = _make_session(status="TRANSCRIBED")
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/export")

        assert response.status_code == 200, response.text
        assert "요약이 아직 없습니다" in response.text


class TestExportTxt:
    def test_txt_returns_transcript_text_only(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session)
        _add_summary(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/export", params={"format": "txt"})

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert response.text == "오늘은 이진 탐색 트리(BST)에 대해 알아보겠습니다."
        assert "한 줄 요약" not in response.text


class TestExportSrt:
    def test_srt_timecode_format_and_content_type(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/export", params={"format": "srt"})

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/x-subrip; charset=utf-8"
        assert (
            "1\n00:00:00,000 --> 00:00:05,200\n오늘은 이진 탐색 트리에 대해 알아보겠습니다.\n"
            in response.text
        )
        assert "2\n00:00:05,200 --> 00:00:11,800\n먼저 삽입 연산부터 보겠습니다.\n" in response.text
