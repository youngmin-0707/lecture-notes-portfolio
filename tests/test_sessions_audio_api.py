"""GET /api/v1/sessions/{id}/audio 테스트 (T-33, US-21).

§5.2 원 스펙에 없던 엔드포인트다 — 세션 상세 화면(T-33)이 오디오를 재생·탐색하려면
필요해서 추가했다. `Range` 요청(탐색 시 브라우저가 보냄) 처리가 핵심 동작이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.models.session import Session


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="7주차",
        course="자료구조",
        status="DONE",
        source="UPLOAD",
        audio_path="data/audio/dummy.upload",
        original_filename="lecture.wav",
        mime_type="audio/wav",
        file_size_bytes=100,
        duration_seconds=3.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


class TestGetSessionAudio:
    def test_returns_404_for_missing_session(self, client) -> None:
        response = client.get("/api/v1/sessions/does-not-exist/audio")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_returns_404_when_audio_file_missing_on_disk(self, client, db_session) -> None:
        session = _make_session(audio_path="/nonexistent/path/audio.wav")
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}/audio")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_streams_full_audio_with_correct_content_type(
        self, client, db_session, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "lecture.wav"
        audio_bytes = b"RIFF" + b"\x00" * 100
        audio_file.write_bytes(audio_bytes)
        session = _make_session(audio_path=str(audio_file), mime_type="audio/wav")
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}/audio")

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "audio/wav"
        assert response.headers.get("accept-ranges") == "bytes"
        assert response.content == audio_bytes

    def test_supports_range_request_for_seeking(self, client, db_session, tmp_path: Path) -> None:
        audio_file = tmp_path / "lecture.wav"
        audio_bytes = bytes(range(256)) * 4  # 1024바이트, 위치 식별이 쉬운 패턴.
        audio_file.write_bytes(audio_bytes)
        session = _make_session(audio_path=str(audio_file), mime_type="audio/wav")
        db_session.add(session)
        db_session.flush()

        response = client.get(
            f"/api/v1/sessions/{session.id}/audio", headers={"Range": "bytes=10-19"}
        )

        assert response.status_code == 206, response.text
        assert response.content == audio_bytes[10:20]
        assert response.headers["content-range"] == f"bytes 10-19/{len(audio_bytes)}"

    def test_content_disposition_is_inline_not_attachment(
        self, client, db_session, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "lecture.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 20)
        session = _make_session(audio_path=str(audio_file))
        db_session.add(session)
        db_session.flush()

        response = client.get(f"/api/v1/sessions/{session.id}/audio")

        disposition = response.headers.get("content-disposition", "")
        assert "attachment" not in disposition
