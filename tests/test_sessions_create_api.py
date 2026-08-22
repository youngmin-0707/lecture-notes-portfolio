"""POST /api/v1/sessions 테스트 (T-09, US-01, US-06, US-07)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.models import Session


@pytest.fixture(autouse=True)
def _isolated_audio_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    storage_dir = tmp_path / "audio"
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(storage_dir))
    monkeypatch.setattr(settings, "MIN_DISK_FREE_BYTES", 1)
    return storage_dir


def _all_files(storage_dir: Path) -> list[Path]:
    if not storage_dir.exists():
        return []
    return list(storage_dir.iterdir())


class TestSuccessfulUpload:
    def test_upload_valid_wav_creates_session_201(
        self, client, db_session, valid_wav_bytes: bytes, _isolated_audio_storage: Path
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture-0820.m4a", valid_wav_bytes, "audio/x-m4a")},
            data={"title": "자료구조 7주차", "course": "자료구조", "autoProcess": "true"},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "자료구조 7주차"
        assert body["course"] == "자료구조"
        assert body["source"] == "UPLOAD"
        assert body["originalFilename"] == "lecture-0820.m4a"
        assert body["fileSizeBytes"] == len(valid_wav_bytes)
        assert body["durationSeconds"] == pytest.approx(2.0, abs=0.05)
        assert "sessionId" in body and body["sessionId"]
        assert "pollAfterSeconds" in body
        assert "recordedAt" in body and "createdAt" in body

        # DB에 세션이 저장되었다 (같은 트랜잭션 내에서 확인).
        stored = db_session.get(Session, body["sessionId"])
        assert stored is not None
        assert stored.file_size_bytes == len(valid_wav_bytes)

    def test_original_filename_not_used_in_storage_path(
        self, client, db_session, valid_wav_bytes: bytes, _isolated_audio_storage: Path
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("../../etc/passwd.wav", valid_wav_bytes, "audio/wav")},
            data={"autoProcess": "false"},
        )

        assert response.status_code == 201, response.text
        session_id = response.json()["sessionId"]
        stored = db_session.get(Session, session_id)
        assert stored is not None
        assert stored.audio_path is not None

        audio_path = Path(stored.audio_path)
        # 저장 경로가 audio storage 디렉토리 하위이며, 사용자 입력이 파일명에 없다.
        assert audio_path.parent == _isolated_audio_storage.resolve() or (
            audio_path.parent == _isolated_audio_storage
        )
        assert "passwd" not in audio_path.name
        assert ".." not in audio_path.name
        assert audio_path.exists()

    def test_default_title_used_when_not_provided(
        self, client, db_session, valid_wav_bytes: bytes
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"].endswith("수업")
        assert body["course"] is None

    def test_status_is_uploaded_for_now_regardless_of_autoprocess(
        self, client, valid_wav_bytes: bytes
    ) -> None:
        """이번 범위(T-01~T-09)는 자동 처리 파이프라인을 연결하지 않는다.

        `autoProcess=true`를 보내도 지금은 UPLOADED로 응답한다 (그룹 C/D에서
        파이프라인이 연결되면 TRANSCRIBING으로 전이하도록 확장될 지점).
        """
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
            data={"autoProcess": "true"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "UPLOADED"


class TestUnsupportedFormat:
    def test_rejects_non_audio_pdf_report(
        self, client, db_session, not_audio_bytes: bytes, _isolated_audio_storage: Path
    ) -> None:
        """US-06: 오디오가 아닌 파일(report.pdf) 업로드는 거부된다."""
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("report.pdf", not_audio_bytes, "application/pdf")},
        )

        assert response.status_code == 415
        body = response.json()
        assert body["error"]["code"] == "UNSUPPORTED_AUDIO_FORMAT"
        assert "requestId" in body

        assert db_session.query(Session).count() == 0
        assert _all_files(_isolated_audio_storage) == []

    def test_rejects_pdf_disguised_as_mp3(
        self,
        client,
        db_session,
        disguised_pdf_as_mp3_bytes: bytes,
        _isolated_audio_storage: Path,
    ) -> None:
        """US-07: 확장자만 mp3로 바꾼 PDF는 실제 내용으로 판별해 거부된다."""
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.mp3", disguised_pdf_as_mp3_bytes, "audio/mpeg")},
        )

        assert response.status_code in (415, 400)
        body = response.json()
        assert body["error"]["code"] in ("UNSUPPORTED_AUDIO_FORMAT", "INVALID_AUDIO_FILE")

        assert db_session.query(Session).count() == 0
        assert _all_files(_isolated_audio_storage) == []


class TestInvalidAudioContent:
    def test_rejects_corrupted_wav(
        self, client, db_session, corrupted_wav_bytes: bytes, _isolated_audio_storage: Path
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", corrupted_wav_bytes, "audio/wav")},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_AUDIO_FILE"
        assert db_session.query(Session).count() == 0
        assert _all_files(_isolated_audio_storage) == []


class TestDurationBounds:
    def test_rejects_audio_shorter_than_1_second(
        self, client, db_session, too_short_wav_bytes: bytes, _isolated_audio_storage: Path
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", too_short_wav_bytes, "audio/wav")},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "AUDIO_TOO_SHORT"
        assert db_session.query(Session).count() == 0
        assert _all_files(_isolated_audio_storage) == []


class TestValidationErrors:
    def test_missing_file_field_is_validation_error(self, client) -> None:
        response = client.post("/api/v1/sessions", data={"title": "제목"})

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_title_over_200_chars_is_validation_error(self, client, valid_wav_bytes: bytes) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
            data={"title": "가" * 201},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_course_over_100_chars_is_validation_error(
        self, client, valid_wav_bytes: bytes
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
            data={"course": "가" * 101},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
