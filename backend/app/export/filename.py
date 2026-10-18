"""내보내기 파일명 생성 (§5.3⑦, T-27).

경로 구분자·제어문자가 파일명에 들어가지 않도록 정규화(sanitize)한다 — 이 값들은 세션의
`title`/`course`에서 오는데, 둘 다 사용자 입력이라 그대로 파일명에 쓰면 경로 순회/헤더
인젝션 위험이 있다.
"""

from __future__ import annotations

import re
from datetime import datetime

# `/`, `\`(경로 구분자)와 모든 제어 문자(개행 포함, \x00-\x1f, \x7f)를 "_"로 치환한다.
_UNSAFE_CHARS_RE = re.compile(r"[\\/\x00-\x1f\x7f]")


def sanitize_filename_part(text: str) -> str:
    """파일명 한 조각(제목/과목 등)에서 경로 구분자·제어문자을 제거한다."""
    cleaned = _UNSAFE_CHARS_RE.sub("_", text).strip()
    return cleaned or "제목없음"


def build_export_filename(
    *, recorded_at: datetime, course: str | None, title: str, extension: str
) -> str:
    """`"YYYY-MM-DD_과목_제목.ext"` 형식 파일명을 만든다 (§5.3⑦ 예시)."""
    parts = [recorded_at.strftime("%Y-%m-%d")]
    if course:
        parts.append(sanitize_filename_part(course))
    parts.append(sanitize_filename_part(title))
    return "_".join(parts) + f".{extension}"
