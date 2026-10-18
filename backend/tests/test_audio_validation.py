"""오디오 검증 유틸 단위 테스트 (T-07, §3.1).

확장자를 신뢰하지 않고 매직 넘버로 실제 형식을 판별하고, `av`로 디코딩 가능 여부와
길이(duration)를 추출한다.
"""

from __future__ import annotations

import io

import pytest

from app.audio.validation import detect_audio_format, probe_audio
from app.core.errors import AppError


class TestDetectAudioFormat:
    def test_detects_wav_by_riff_wave_magic(self, valid_wav_bytes: bytes) -> None:
        result = detect_audio_format(valid_wav_bytes)
        assert result is not None
        format_key, mime_type = result
        assert format_key == "wav"
        assert mime_type == "audio/wav"

    def test_detects_mp3_by_id3_tag(self) -> None:
        header = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 32
        result = detect_audio_format(header)
        assert result is not None
        assert result[0] == "mp3"
        assert result[1] == "audio/mpeg"

    def test_detects_mp3_by_frame_sync(self) -> None:
        header = b"\xff\xfb\x90\x00" + b"\x00" * 32
        result = detect_audio_format(header)
        assert result is not None
        assert result[0] == "mp3"

    def test_detects_mp4_m4a_by_ftyp_box(self) -> None:
        header = b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00" + b"\x00" * 16
        result = detect_audio_format(header)
        assert result is not None
        assert result[0] == "mp4"
        assert result[1] == "audio/mp4"

    def test_detects_ogg_by_oggs_magic(self) -> None:
        header = b"OggS" + b"\x00" * 32
        result = detect_audio_format(header)
        assert result is not None
        assert result[0] == "ogg"

    def test_detects_flac_by_flac_magic(self) -> None:
        header = b"fLaC" + b"\x00" * 32
        result = detect_audio_format(header)
        assert result is not None
        assert result[0] == "flac"

    def test_detects_webm_by_ebml_magic(self) -> None:
        header = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
        result = detect_audio_format(header)
        assert result is not None
        assert result[0] == "webm"

    def test_rejects_pdf_disguised_as_mp3(self, disguised_pdf_as_mp3_bytes: bytes) -> None:
        result = detect_audio_format(disguised_pdf_as_mp3_bytes)
        assert result is None

    def test_rejects_plain_text(self, not_audio_bytes: bytes) -> None:
        result = detect_audio_format(not_audio_bytes)
        assert result is None

    def test_rejects_empty_bytes(self) -> None:
        assert detect_audio_format(b"") is None


class TestProbeAudio:
    def test_valid_wav_reports_duration_and_is_decodable(self, tmp_path, make_wav_bytes) -> None:
        path = tmp_path / "lecture.bin"
        path.write_bytes(make_wav_bytes(3.0))

        result = probe_audio(path)

        assert result.duration_seconds == pytest.approx(3.0, abs=0.05)

    def test_corrupted_wav_raises_invalid_audio_file(
        self, tmp_path, corrupted_wav_bytes: bytes
    ) -> None:
        path = tmp_path / "broken.bin"
        path.write_bytes(corrupted_wav_bytes)

        with pytest.raises(AppError) as exc_info:
            probe_audio(path)
        assert exc_info.value.code == "INVALID_AUDIO_FILE"

    def test_non_audio_content_raises_invalid_audio_file(
        self, tmp_path, not_audio_bytes: bytes
    ) -> None:
        path = tmp_path / "notaudio.bin"
        path.write_bytes(not_audio_bytes)

        with pytest.raises(AppError) as exc_info:
            probe_audio(path)
        assert exc_info.value.code == "INVALID_AUDIO_FILE"

    def test_missing_file_raises_invalid_audio_file(self, tmp_path) -> None:
        with pytest.raises(AppError) as exc_info:
            probe_audio(tmp_path / "does-not-exist.bin")
        assert exc_info.value.code == "INVALID_AUDIO_FILE"


def test_detect_audio_format_ignores_extension_and_only_uses_bytes(
    disguised_pdf_as_mp3_bytes: bytes,
) -> None:
    """파일명이 뭐든(.mp3든 .wav든) 판별 결과는 바이트 내용에만 의존해야 한다."""
    buf = io.BytesIO(disguised_pdf_as_mp3_bytes)
    header = buf.read(64)
    assert detect_audio_format(header) is None
