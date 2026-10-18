"""POST /api/v1/sessions/export 테스트 (2026-10-07, 여러 세션 요약을 ZIP 하나로 내려받기)."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript


def _add_done_session(db_session, *, with_summary: bool = True, **overrides) -> Session:
    defaults = dict(
        title="7주차",
        course="자료구조",
        status="DONE",
        source="UPLOAD",
        audio_path=None,
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=120.0,
        recorded_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    session = Session(**defaults)
    db_session.add(session)
    db_session.flush()
    db_session.add(
        Transcript(
            session_id=session.id,
            text_raw="전사 원문입니다.",
            text_corrected="전사 보정본입니다.",
            language="ko",
            provider="fake",
            provider_model="fake-large",
        )
    )
    if with_summary:
        db_session.add(
            Summary(
                session_id=session.id,
                content_markdown=f"## 한 줄 요약\n{session.title} 요약 본문",
                key_points=[],
                concepts=[],
                code_snippets=[],
                action_items=[],
                keywords=[],
                provider="fake",
                provider_model="fake-model",
            )
        )
    db_session.flush()
    return session


def _post_export(client, session_ids: list[str]):
    return client.post("/api/v1/sessions/export", json={"sessionIds": session_ids})


def _open_zip(response) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(response.content))


class TestBulkExportZip:
    def test_zip_contains_one_markdown_file_per_session(self, client, db_session) -> None:
        first = _add_done_session(db_session, title="7주차")
        second = _add_done_session(db_session, title="8주차")

        response = _post_export(client, [first.id, second.id])

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        assert sorted(_open_zip(response).namelist()) == [
            "2026-08-20_자료구조_7주차.md",
            "2026-08-20_자료구조_8주차.md",
        ]

    def test_each_file_holds_that_sessions_summary(self, client, db_session) -> None:
        first = _add_done_session(db_session, title="7주차")
        second = _add_done_session(db_session, title="8주차")

        archive = _open_zip(_post_export(client, [first.id, second.id]))

        content = archive.read("2026-08-20_자료구조_8주차.md").decode("utf-8")
        assert "# 8주차" in content
        assert "8주차 요약 본문" in content
        assert "7주차 요약 본문" not in content

    def test_files_contain_summary_only_without_transcript(self, client, db_session) -> None:
        session = _add_done_session(db_session)

        archive = _open_zip(_post_export(client, [session.id]))

        content = archive.read(archive.namelist()[0]).decode("utf-8")
        assert "전사 전문" not in content
        assert "전사 보정본입니다." not in content

    def test_sessions_with_same_filename_do_not_overwrite_each_other(
        self, client, db_session
    ) -> None:
        first = _add_done_session(db_session)
        second = _add_done_session(db_session)

        archive = _open_zip(_post_export(client, [first.id, second.id]))

        assert sorted(archive.namelist()) == [
            "2026-08-20_자료구조_7주차 (2).md",
            "2026-08-20_자료구조_7주차.md",
        ]

    def test_duplicate_ids_are_exported_once(self, client, db_session) -> None:
        session = _add_done_session(db_session)

        archive = _open_zip(_post_export(client, [session.id, session.id]))

        assert archive.namelist() == ["2026-08-20_자료구조_7주차.md"]

    def test_content_disposition_is_zip_attachment(self, client, db_session) -> None:
        session = _add_done_session(db_session)

        disposition = _post_export(client, [session.id]).headers["content-disposition"]

        assert disposition.startswith("attachment;")
        assert disposition.endswith(".zip")


class TestBulkExportErrors:
    def test_unknown_session_id_returns_404(self, client, db_session) -> None:
        session = _add_done_session(db_session)

        response = _post_export(client, [session.id, "does-not-exist"])

        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_session_without_summary_returns_409(self, client, db_session) -> None:
        session = _add_done_session(db_session, with_summary=False)

        response = _post_export(client, [session.id])

        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "SUMMARY_NOT_READY"

    def test_empty_id_list_returns_400(self, client) -> None:
        response = _post_export(client, [])

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
