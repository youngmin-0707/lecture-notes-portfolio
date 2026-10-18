"""텍스트 업로드 판별·디코딩·길이 검증 단위 테스트 (2026-09-14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.text.validation import (
    decode_text_upload,
    is_text_upload,
    load_text_upload,
    text_mime_type,
    text_upload_extension,
    validate_text_length,
)

LONG_ENOUGH_TEXT = "오늘 수업에서는 이진 탐색 트리의 삽입과 삭제를 다뤘다." * 2


class TestExtensionDetection:
    @pytest.mark.parametrize(
        "filename", ["notes.txt", "NOTES.TXT", "강의.md", "readme.markdown", "a.b.txt"]
    )
    def test_text_extensions_are_accepted(self, filename: str) -> None:
        assert is_text_upload(filename) is True

    @pytest.mark.parametrize(
        "filename", ["lecture.mp3", "lecture.wav", "report.pdf", "noextension", None, ""]
    )
    def test_non_text_extensions_are_rejected(self, filename: str | None) -> None:
        assert is_text_upload(filename) is False
        assert text_upload_extension(filename) is None

    def test_mime_type_per_extension(self) -> None:
        assert text_mime_type("notes.txt") == "text/plain"
        assert text_mime_type("notes.md") == "text/markdown"
        assert text_mime_type("notes.markdown") == "text/markdown"


class TestDecoding:
    def test_decodes_utf8(self) -> None:
        assert decode_text_upload("한글 강의 노트".encode()) == "한글 강의 노트"

    def test_decodes_utf8_with_bom(self) -> None:
        """메모장이 저장한 BOM 붙은 파일도 그대로 읽는다 (BOM은 본문에 남지 않는다)."""
        assert decode_text_upload("﻿강의 노트".encode()) == "강의 노트"

    def test_decodes_cp949(self) -> None:
        assert decode_text_upload("한글 강의 노트".encode("cp949")) == "한글 강의 노트"

    def test_normalizes_windows_newlines(self) -> None:
        assert decode_text_upload(b"first\r\nsecond\rthird") == "first\nsecond\nthird"

    def test_rejects_binary_with_null_bytes(self) -> None:
        with pytest.raises(AppError) as exc_info:
            decode_text_upload(b"PK\x03\x04\x00\x00binary garbage")
        assert exc_info.value.code == "INVALID_TEXT_FILE"

    def test_rejects_undecodable_bytes(self) -> None:
        with pytest.raises(AppError) as exc_info:
            decode_text_upload(b"\xff\xfe\xfd\xfc" * 10)
        assert exc_info.value.code == "INVALID_TEXT_FILE"


class TestLengthBounds:
    def test_accepts_normal_length(self) -> None:
        validate_text_length(LONG_ENOUGH_TEXT)  # 예외가 나지 않아야 한다.

    def test_rejects_too_short(self) -> None:
        with pytest.raises(AppError) as exc_info:
            validate_text_length("짧다")
        assert exc_info.value.code == "TEXT_TOO_SHORT"

    def test_whitespace_only_is_too_short(self) -> None:
        with pytest.raises(AppError) as exc_info:
            validate_text_length("   \n\n\t  ")
        assert exc_info.value.code == "TEXT_TOO_SHORT"

    def test_rejects_too_long(self) -> None:
        with pytest.raises(AppError) as exc_info:
            validate_text_length("가" * (settings.MAX_TEXT_CHARACTERS + 1))
        assert exc_info.value.code == "TEXT_TOO_LONG"


class TestLoadTextUpload:
    def test_reads_validates_and_strips(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.txt"
        path.write_text(f"\n\n{LONG_ENOUGH_TEXT}\n\n", encoding="utf-8")

        assert load_text_upload(path) == LONG_ENOUGH_TEXT

    def test_raises_on_too_short_file(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.txt"
        path.write_text("짧은 메모", encoding="utf-8")

        with pytest.raises(AppError) as exc_info:
            load_text_upload(path)
        assert exc_info.value.code == "TEXT_TOO_SHORT"
