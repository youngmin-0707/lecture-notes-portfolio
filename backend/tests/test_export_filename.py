"""파일명/헤더 생성 유닛 테스트 (T-27, §5.3⑦)."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import unquote

from app.export.content_disposition import build_content_disposition
from app.export.filename import build_export_filename, sanitize_filename_part


class TestSanitizeFilenamePart:
    def test_removes_path_separators(self) -> None:
        assert "/" not in sanitize_filename_part("자료구조/7주차")
        assert "\\" not in sanitize_filename_part("자료구조\\7주차")

    def test_removes_control_characters(self) -> None:
        result = sanitize_filename_part("제목\n\r\x00본문")
        assert "\n" not in result
        assert "\r" not in result
        assert "\x00" not in result

    def test_empty_input_falls_back(self) -> None:
        assert sanitize_filename_part("") == "제목없음"

    def test_whitespace_only_input_falls_back(self) -> None:
        assert sanitize_filename_part("   ") == "제목없음"

    def test_path_separators_replaced_not_stripped_to_empty(self) -> None:
        # 구분자를 "_"로 치환하므로 빈 문자열이 되지 않는다 — 안전하되 의미는 사라짐, OK.
        assert sanitize_filename_part("///") == "___"

    def test_normal_text_untouched(self) -> None:
        assert sanitize_filename_part("자료구조 7주차") == "자료구조 7주차"


class TestBuildExportFilename:
    def test_matches_spec_example_format(self) -> None:
        filename = build_export_filename(
            recorded_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            course="자료구조",
            title="7주차",
            extension="md",
        )
        assert filename == "2026-08-20_자료구조_7주차.md"

    def test_no_course_omits_that_segment(self) -> None:
        filename = build_export_filename(
            recorded_at=datetime(2026, 8, 20, tzinfo=UTC),
            course=None,
            title="7주차",
            extension="md",
        )
        assert filename == "2026-08-20_7주차.md"

    def test_path_traversal_attempt_in_title_is_sanitized(self) -> None:
        """`/`가 사라지면 ".."이 남아있어도 경로 세그먼트로 동작할 수 없어 안전하다."""
        filename = build_export_filename(
            recorded_at=datetime(2026, 8, 20, tzinfo=UTC),
            course=None,
            title="../../etc/passwd",
            extension="md",
        )
        assert "/" not in filename
        assert "\\" not in filename


class TestBuildContentDisposition:
    def test_includes_ascii_fallback_and_utf8_extended_filename(self) -> None:
        header = build_content_disposition("2026-08-20_자료구조_7주차.md")

        assert header.startswith("attachment; ")
        assert 'filename="export.md"' in header
        assert "filename*=UTF-8''" in header

        encoded_part = header.split("filename*=UTF-8''", 1)[1]
        assert unquote(encoded_part) == "2026-08-20_자료구조_7주차.md"

    def test_header_value_is_ascii_safe(self) -> None:
        header = build_content_disposition("2026-08-20_자료구조_7주차.srt")
        header.encode("latin-1")  # Starlette가 실제로 요구하는 인코딩 — 실패하면 예외.
