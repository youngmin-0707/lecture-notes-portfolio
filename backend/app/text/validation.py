"""텍스트 업로드 판별·디코딩·길이 검증 (2026-09-14).

**오디오와 달리 확장자를 본다.** `app/audio/validation.py`는 매직 넘버만으로 형식을
판별하지만(US-07), 일반 텍스트 파일에는 매직 넘버 자체가 없다 — 임의의 바이트열이 그냥
"우연히 UTF-8로 디코딩되는" 일이 흔하므로(예: ASCII만 든 PDF 조각), 내용만으로 "이건
텍스트 파일이다"라고 단정하면 오디오로 올렸다가 깨진 파일이 조용히 텍스트로 처리되는
사고가 난다. 그래서 텍스트 경로는 **확장자 화이트리스트(`TEXT_UPLOAD_EXTENSIONS`)로 먼저
진입 조건을 정하고, 그 다음 내용이 실제로 디코딩되는지 확인**하는 2단 구조로 간다. 확장자를
속여도 실행되는 것이 아니라 LLM 요약 입력으로 쓰일 뿐이므로 §3.1의 위협 모델(위장 파일로
디코더를 공격)과는 성격이 다르다.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError

# 허용 확장자(소문자). `.md`/`.markdown`은 요약 프롬프트에 그대로 넣어도 문제없는 평문이다.
TEXT_UPLOAD_EXTENSIONS: tuple[str, ...] = ("txt", "md", "markdown")

_EXTENSION_MIME_TYPES: dict[str, str] = {
    "txt": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
}

# BOM이 붙은 메모장 저장본(utf-8-sig)과 윈도우 한글 인코딩(cp949, EUC-KR 상위호환)까지는
# 받아준다 — 실사용에서 가장 흔한 두 가지다. 그 외 인코딩은 INVALID_TEXT_FILE로 거부한다.
_DECODE_CANDIDATES: tuple[str, ...] = ("utf-8-sig", "cp949")

# 제어문자가 섞여 있으면 텍스트가 아니라 바이너리로 본다(줄바꿈/탭 제외).
_ALLOWED_CONTROL_CHARACTERS = frozenset("\n\r\t")


def text_upload_extension(filename: str | None) -> str | None:
    """파일명이 텍스트 업로드 확장자면 그 확장자(소문자)를, 아니면 `None`을 돌려준다."""
    if not filename or "." not in filename:
        return None
    extension = filename.rsplit(".", 1)[-1].lower()
    return extension if extension in TEXT_UPLOAD_EXTENSIONS else None


def is_text_upload(filename: str | None) -> bool:
    return text_upload_extension(filename) is not None


def text_mime_type(filename: str | None) -> str:
    extension = text_upload_extension(filename)
    return _EXTENSION_MIME_TYPES.get(extension or "", "text/plain")


def decode_text_upload(raw: bytes) -> str:
    """업로드된 바이트를 텍스트로 디코딩한다.

    디코딩이 안 되거나 제어문자(=바이너리)가 섞여 있으면 `AppError("INVALID_TEXT_FILE")`.
    """
    for encoding in _DECODE_CANDIDATES:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _contains_binary_control_characters(text):
            raise AppError("INVALID_TEXT_FILE")
        return _normalize_newlines(text)
    raise AppError("INVALID_TEXT_FILE")


def _contains_binary_control_characters(text: str) -> bool:
    return any(ch < " " and ch not in _ALLOWED_CONTROL_CHARACTERS for ch in text) or "\x00" in text


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def validate_text_length(text: str) -> None:
    """§3.1 오디오 길이 검증(`validate_duration_seconds`)에 대응하는 텍스트판 검증.

    요약할 내용이 사실상 없는 파일(빈 파일/한 줄짜리)과, 컨텍스트를 통째로 넘겨봐야 의미가
    없는 과도하게 긴 파일을 걸러낸다.
    """
    length = len(text.strip())
    if length < settings.MIN_TEXT_CHARACTERS:
        raise AppError("TEXT_TOO_SHORT")
    if length > settings.MAX_TEXT_CHARACTERS:
        raise AppError("TEXT_TOO_LONG")


def load_text_upload(path: Path) -> str:
    """저장된 업로드 파일을 텍스트로 읽어 검증까지 마친 본문을 돌려준다.

    텍스트는 오디오와 달리 파일을 계속 보관할 이유가 없다 — 호출부가 이 반환값을
    `transcripts`에 저장한 뒤 원본 파일은 지운다.
    """
    text = decode_text_upload(Path(path).read_bytes())
    validate_text_length(text)
    return text.strip()
