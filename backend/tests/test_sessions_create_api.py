"""POST /api/v1/sessions 테스트 (T-09, US-01, US-06, US-07)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.models import Session, Summary, Transcript


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

        from app.models.session import Session as SessionModel

        session = db_session.get(SessionModel, body["sessionId"])
        # 2026-08-30: 제목을 직접 안 정했으니, 요약 완료 후 자동 제목으로 덮어써도 된다.
        assert session.title_customized is False

    def test_explicit_title_marks_customized(
        self, client, db_session, valid_wav_bytes: bytes
    ) -> None:
        """2026-08-30: 업로드 시 제목을 직접 입력했다면 이후 요약이 자동으로 덮어쓰면 안 된다."""
        response = client.post(
            "/api/v1/sessions",
            data={"title": "내가 정한 제목"},
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "내가 정한 제목"

        from app.models.session import Session as SessionModel

        session = db_session.get(SessionModel, body["sessionId"])
        assert session.title_customized is True

    def test_autoprocess_true_transitions_to_transcribing(
        self, client, valid_wav_bytes: bytes
    ) -> None:
        """US-02, T-19: autoProcess=true(기본값)면 응답 시점 status가 TRANSCRIBING이고,
        전사→요약 파이프라인이 백그라운드로 예약된다 (§5.3①)."""
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
            data={"autoProcess": "true"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "TRANSCRIBING"

    def test_autoprocess_false_stays_uploaded(self, client, valid_wav_bytes: bytes) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture.wav", valid_wav_bytes, "audio/wav")},
            data={"autoProcess": "false"},
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


class TestTextFileUpload:
    """텍스트 파일(.txt/.md) 업로드 — 전사를 건너뛰고 곧바로 요약으로 이어진다 (2026-09-14)."""

    def test_txt_upload_creates_session_with_transcript_and_starts_summarizing(
        self, client, db_session, _isolated_audio_storage: Path
    ) -> None:
        content = (
            "오늘 수업에서는 이진 탐색 트리의 삽입과 삭제를 다뤘다.\n시간복잡도는 O(log n)이다."
        )

        response = client.post(
            "/api/v1/sessions",
            files={"file": ("lecture-note.txt", content.encode(), "text/plain")},
            data={"title": "자료구조 8주차", "course": "자료구조", "autoProcess": "true"},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["source"] == "TEXT"
        # 전사 단계를 건너뛰므로 TRANSCRIBING이 아니라 바로 SUMMARIZING이다.
        assert body["status"] == "SUMMARIZING"
        assert body["durationSeconds"] is None
        assert body["originalFilename"] == "lecture-note.txt"
        assert body["fileSizeBytes"] == len(content.encode())

        stored = db_session.get(Session, body["sessionId"])
        assert stored is not None
        assert stored.mime_type == "text/plain"
        # 오디오가 없는 세션이므로 저장 경로도, 남은 업로드 파일도 없다.
        assert stored.audio_path is None
        assert _all_files(_isolated_audio_storage) == []

        transcript = (
            db_session.query(Transcript).filter(Transcript.session_id == stored.id).one_or_none()
        )
        assert transcript is not None
        assert transcript.text_raw == content
        assert transcript.provider == "text_upload"
        assert transcript.segments == []

    def test_markdown_upload_is_accepted(self, client, db_session) -> None:
        content = "# 8주차\n\n- 이진 탐색 트리의 삽입과 삭제를 다뤘다.\n- 시간복잡도는 O(log n)."

        response = client.post(
            "/api/v1/sessions",
            files={"file": ("note.md", content.encode(), "text/markdown")},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "SUMMARIZING"
        stored = db_session.get(Session, body["sessionId"])
        assert stored.mime_type == "text/markdown"

    def test_autoprocess_false_stays_transcribed(self, client) -> None:
        """자동 처리를 끄면 "전사까지는 끝난" 상태(TRANSCRIBED)에서 멈춘다."""
        content = "오늘 수업에서는 이진 탐색 트리의 삽입과 삭제를 다뤘다." * 2

        response = client.post(
            "/api/v1/sessions",
            files={"file": ("note.txt", content.encode(), "text/plain")},
            data={"autoProcess": "false"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "TRANSCRIBED"

    def test_cp949_encoded_text_is_accepted(self, client, db_session) -> None:
        content = "오늘 수업에서는 이진 탐색 트리의 삽입과 삭제를 다뤘다." * 2

        response = client.post(
            "/api/v1/sessions",
            files={"file": ("note.txt", content.encode("cp949"), "text/plain")},
        )

        assert response.status_code == 201, response.text
        stored = db_session.get(Session, response.json()["sessionId"])
        transcript = (
            db_session.query(Transcript).filter(Transcript.session_id == stored.id).one_or_none()
        )
        assert transcript is not None and transcript.text_raw == content

    def test_rejects_too_short_text(
        self, client, db_session, _isolated_audio_storage: Path
    ) -> None:
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("note.txt", "짧은 메모".encode(), "text/plain")},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "TEXT_TOO_SHORT"
        assert db_session.query(Session).count() == 0
        assert _all_files(_isolated_audio_storage) == []

    def test_rejects_binary_disguised_as_txt(
        self, client, db_session, _isolated_audio_storage: Path
    ) -> None:
        """확장자만 .txt인 바이너리는 디코딩 단계에서 걸러진다."""
        response = client.post(
            "/api/v1/sessions",
            files={"file": ("note.txt", b"PK\x03\x04\x00\x00" * 30, "text/plain")},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_TEXT_FILE"
        assert db_session.query(Session).count() == 0
        assert _all_files(_isolated_audio_storage) == []

    def test_rejects_text_file_over_size_limit(
        self, client, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MAX_TEXT_UPLOAD_SIZE_BYTES", 1024)

        response = client.post(
            "/api/v1/sessions",
            files={"file": ("note.txt", b"a" * 2048, "text/plain")},
        )

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
        assert db_session.query(Session).count() == 0

    def test_text_session_runs_to_done_without_stt(self, real_client, engine) -> None:
        """실제 커밋 + 백그라운드 실행 경로: 텍스트 업로드 한 번으로 요약(DONE)까지 간다."""
        from sqlalchemy.orm import Session as ORMSession

        content = "오늘 수업에서는 이진 탐색 트리의 삽입과 삭제를 다뤘다." * 3

        response = real_client.post(
            "/api/v1/sessions",
            files={"file": ("note.txt", content.encode(), "text/plain")},
        )
        assert response.status_code == 201, response.text
        session_id = response.json()["sessionId"]

        check_db = ORMSession(bind=engine, future=True)
        try:
            persisted = check_db.get(Session, session_id)
            assert persisted.status == "DONE"
            # 전사는 업로드된 텍스트 그대로여야 한다 (STT가 끼어들지 않았다).
            transcript = (
                check_db.query(Transcript).filter(Transcript.session_id == session_id).one()
            )
            assert transcript.text_raw == content
            assert transcript.provider == "text_upload"
            assert check_db.query(Summary).filter(Summary.session_id == session_id).count() == 1
        finally:
            check_db.query(Summary).filter(Summary.session_id == session_id).delete()
            check_db.query(Transcript).filter(Transcript.session_id == session_id).delete()
            check_db.query(Session).filter(Session.id == session_id).delete()
            check_db.commit()
            check_db.close()
