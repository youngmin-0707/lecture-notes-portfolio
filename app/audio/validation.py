"""오디오 형식 판별·무결성 검증·길이 추출 (§3.1).

**확장자를 신뢰하지 않는다.** `detect_audio_format`은 파일 시작 바이트(매직 넘버/컨테이너
헤더)만으로 실제 형식을 판별한다. `probe_audio`는 `av`(PyAV, ffmpeg 라이브러리를 정적
번들링)로 실제 디코딩 가능 여부와 길이(duration)를 확인한다 — 시스템에 Homebrew/ffmpeg가
없어도 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import av.error

from app.core.config import settings
from app.core.errors import AppError

# 매직 넘버 판별 시 필요한 최소 바이트 수. 스트리밍 업로드 시 이만큼만 앞부분에서 확보하면 된다.
MAGIC_HEADER_SIZE = 64

# §3.1: mp3, m4a, wav, webm, ogg, flac, mp4, mpeg — mp3/mpeg는 동일 컨테이너(MPEG 오디오
# 프레임 또는 ID3 태그)이므로 "mp3" 하나로, m4a/mp4는 동일 컨테이너(ISO BMFF `ftyp` 박스)
# 이므로 "mp4" 하나로 묶어 판별한다.
_FORMAT_MIME_TYPES: dict[str, str] = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "mp4": "audio/mp4",
    "mp3": "audio/mpeg",
}


def detect_audio_format(header: bytes) -> tuple[str, str] | None:
    """헤더 바이트로 실제 오디오 컨테이너 형식을 판별한다.

    반환: `(format_key, mime_type)` 또는 인식할 수 없으면 `None`.
    확장자는 전혀 참조하지 않는다 — 오직 바이트 내용만 본다 (US-07).
    """
    if header[0:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav", _FORMAT_MIME_TYPES["wav"]
    if header[0:4] == b"fLaC":
        return "flac", _FORMAT_MIME_TYPES["flac"]
    if header[0:4] == b"OggS":
        return "ogg", _FORMAT_MIME_TYPES["ogg"]
    if header[0:4] == b"\x1a\x45\xdf\xa3":
        return "webm", _FORMAT_MIME_TYPES["webm"]
    if header[4:8] == b"ftyp":
        return "mp4", _FORMAT_MIME_TYPES["mp4"]
    if header[0:3] == b"ID3":
        return "mp3", _FORMAT_MIME_TYPES["mp3"]
    if len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
        return "mp3", _FORMAT_MIME_TYPES["mp3"]
    return None


@dataclass(frozen=True)
class AudioProbeResult:
    duration_seconds: float


def _duration_from_container_metadata(container, stream) -> float | None:
    if container.duration is not None:
        return container.duration / 1_000_000  # AV_TIME_BASE = 1e6 (마이크로초)
    if stream.duration is not None and stream.time_base is not None:
        return float(stream.duration * stream.time_base)
    return None


def _duration_by_full_decode(container, stream) -> float | None:
    """컨테이너에 duration 메타데이터가 없을 때(예: 일부 ogg/webm) 전체 디코딩으로 추정한다."""
    end_seconds = 0.0
    sample_rate = stream.codec_context.sample_rate
    for frame in container.decode(stream):
        if frame.pts is not None and frame.time_base is not None:
            start = float(frame.pts * frame.time_base)
        elif frame.time is not None:
            start = frame.time
        else:
            start = end_seconds
        samples = getattr(frame, "samples", 0) or 0
        end = start + (samples / sample_rate if sample_rate else 0.0)
        end_seconds = max(end_seconds, end)
    return end_seconds or None


def probe_audio(path: Path) -> AudioProbeResult:
    """오디오 파일을 열어 디코딩 가능 여부를 확인하고 길이(초)를 추출한다.

    디코딩이 불가능하거나(§3.1 무결성), 오디오 스트림이 없거나, 길이를 알 수 없으면
    `AppError("INVALID_AUDIO_FILE")`를 던진다.
    """
    try:
        container = av.open(str(path))
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise AppError("INVALID_AUDIO_FILE") from exc

    try:
        audio_streams = [s for s in container.streams if s.type == "audio"]
        if not audio_streams:
            raise AppError("INVALID_AUDIO_FILE")
        stream = audio_streams[0]

        try:
            decoded_first_frame = next(iter(container.decode(stream)), None)
        except (av.error.FFmpegError, OSError, ValueError) as exc:
            raise AppError("INVALID_AUDIO_FILE") from exc
        if decoded_first_frame is None:
            raise AppError("INVALID_AUDIO_FILE")

        duration = _duration_from_container_metadata(container, stream)
        if duration is None:
            container.seek(0)
            try:
                duration = _duration_by_full_decode(container, stream)
            except (av.error.FFmpegError, OSError, ValueError) as exc:
                raise AppError("INVALID_AUDIO_FILE") from exc
        if duration is None:
            raise AppError("INVALID_AUDIO_FILE")
    finally:
        container.close()

    return AudioProbeResult(duration_seconds=duration)


def validate_duration_seconds(duration_seconds: float) -> None:
    """§3.1: 1초 초과 ~ 최대 240분(설정값)만 허용한다."""
    if duration_seconds <= settings.MIN_AUDIO_DURATION_SECONDS:
        raise AppError("AUDIO_TOO_SHORT")
    if duration_seconds > settings.MAX_AUDIO_DURATION_SECONDS:
        raise AppError("AUDIO_TOO_LONG")
