"""GET /api/v1/sessions/{id} + GET /api/v1/sessions/{id}/transcript 테스트 (T-13, US-03, US-04)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.enums import SessionStatus
from app.models.session import Session
from app.models.transcript import Transcript, TranscriptSegment
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


def _add_transcript(db_session, session: Session, *, corrected: str | None = None) -> Transcript:
    transcript = Transcript(
        session_id=session.id,
        text_raw="오늘은 이진 탐색 트리에 대해 알아보겠습니다. 먼저 삽입 연산부터 보겠습니다.",
        text_corrected=corrected,
        language="ko",
        provider="fake",
        provider_model="fake-large",
        elapsed_seconds=1.5,
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


@pytest.fixture(autouse=True)
def _clear_progress_store():
    progress_module.clear_all_progress()
    yield
    progress_module.clear_all_progress()


class TestSessionDetailNotFound:
    def test_returns_404_session_not_found(self, client) -> None:
        response = client.get("/api/v1/sessions/does-not-exist")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


class TestSessionDetailDone:
    def test_transcribed_session_shows_transcript_available(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["sessionId"] == session.id
        assert body["status"] == "TRANSCRIBED"
        assert body["title"] == "자료구조 7주차"
        assert body["transcript"]["available"] is True
        assert body["transcript"]["provider"] == "fake"
        assert body["transcript"]["providerModel"] == "fake-large"
        assert body["transcript"]["characterCount"] > 0
        assert body["summary"] is None
        assert body["errorCode"] is None


class TestSessionDetailProcessing:
    def test_transcribing_status_includes_progress_and_poll_after(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBING.value)
        db_session.add(session)
        db_session.flush()
        progress_module.set_progress(
            session.id, stage="TRANSCRIBING", percent=42.5, eta_seconds=260
        )

        response = client.get(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "TRANSCRIBING"
        assert body["progress"] == {"stage": "TRANSCRIBING", "percent": 42.5, "etaSeconds": 260}
        assert body["transcript"]["available"] is False
        assert body["summary"] is None
        assert "pollAfterSeconds" in body and body["pollAfterSeconds"] > 0

    def test_transcribing_without_progress_entry_falls_back_to_default(
        self, client, db_session
    ) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBING.value)
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["progress"]["stage"] == "TRANSCRIBING"
        assert body["progress"]["percent"] == 0.0


class TestSessionDetailFailed:
    def test_failed_session_returns_200_with_error_fields(self, client, db_session) -> None:
        session = _make_session(
            status=SessionStatus.FAILED.value,
            error_code="STT_FAILED",
            error_message="전사에 실패했습니다.",
        )
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["errorCode"] == "STT_FAILED"
        assert body["errorMessage"] == "전사에 실패했습니다."
        assert body["transcript"]["available"] is False
        assert body["summary"] is None

    def test_failed_session_with_preserved_transcript_shows_available(
        self, client, db_session
    ) -> None:
        """US-08 전제: 요약 실패해도 전사는 보존된다. 조회 시에도 available=true여야 한다."""
        session = _make_session(
            status=SessionStatus.FAILED.value, error_code="LLM_FAILED", error_message="요약 실패"
        )
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["transcript"]["available"] is True


class TestTranscriptEndpoint:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.get("/api/v1/sessions/does-not-exist/transcript")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_returns_409_when_transcript_not_ready(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.UPLOADED.value)
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}/transcript")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TRANSCRIPT_NOT_READY"

    def test_returns_text_and_segments_in_seq_order(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session)

        response = client.get(f"/api/v1/sessions/{session.id}/transcript")

        assert response.status_code == 200
        body = response.json()
        assert body["sessionId"] == session.id
        assert body["language"] == "ko"
        assert body["text"].startswith("오늘은 이진 탐색 트리")
        assert [s["seq"] for s in body["segments"]] == [0, 1]
        assert body["segments"][0]["startSeconds"] == pytest.approx(0.0)
        assert body["segments"][0]["endSeconds"] == pytest.approx(5.2)
        assert body["segments"][1]["startSeconds"] == pytest.approx(5.2)
        # US-04: 시작 시각 단조 증가, 구간 비중첩.
        starts = [s["startSeconds"] for s in body["segments"]]
        assert starts == sorted(starts)

    def test_corrected_true_falls_back_to_raw_when_no_correction_yet(
        self, client, db_session
    ) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        transcript = _add_transcript(db_session, session, corrected=None)

        response = client.get(f"/api/v1/sessions/{session.id}/transcript?corrected=true")

        assert response.status_code == 200
        body = response.json()
        assert body["corrected"] is False  # 보정본이 없어 원본으로 폴백했음을 정직하게 반영
        assert body["text"] == transcript.text_raw

    def test_corrected_true_uses_corrected_text_when_available(self, client, db_session) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        _add_transcript(db_session, session, corrected="오늘은 이진 탐색 트리(BST)에 대해...")

        response = client.get(f"/api/v1/sessions/{session.id}/transcript?corrected=true")

        assert response.status_code == 200
        body = response.json()
        assert body["corrected"] is True
        assert body["text"] == "오늘은 이진 탐색 트리(BST)에 대해..."

    def test_corrected_false_uses_raw_text_even_when_corrected_exists(
        self, client, db_session
    ) -> None:
        session = _make_session(status=SessionStatus.TRANSCRIBED.value)
        db_session.add(session)
        db_session.flush()
        transcript = _add_transcript(db_session, session, corrected="보정된 텍스트")

        response = client.get(f"/api/v1/sessions/{session.id}/transcript?corrected=false")

        assert response.status_code == 200
        body = response.json()
        assert body["corrected"] is False
        assert body["text"] == transcript.text_raw
