"""`Content-Disposition` 헤더 값 생성 (T-27).

파일명에 한글 등 비ASCII 문자가 들어가는데, HTTP 헤더 값은 ASCII/Latin-1만 담을 수 있다
(그대로 넣으면 `UnicodeEncodeError`). RFC 6266/5987의 `filename*=UTF-8''<percent-encoded>`
확장 문법으로 실제 파일명을 전달하고, 이를 모르는 구형 클라이언트를 위한 ASCII 폴백
`filename="export.ext"`도 함께 둔다.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def build_content_disposition(filename: str) -> str:
    extension = Path(filename).suffix or ""
    fallback = f"export{extension}"
    encoded = quote(filename)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
