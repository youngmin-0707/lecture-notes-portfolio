"""세션 관련 Pydantic 요청/응답 스키마 (§5.3)."""

from __future__ import annotations

from app.schemas.common import CamelModel, UtcDateTime


class SessionCreateResponse(CamelModel):
    """POST /api/v1/sessions 응답 (§5.3 ①)."""

    session_id: str
    title: str
    course: str | None
    status: str
    source: str
    original_filename: str
    file_size_bytes: int
    duration_seconds: float | None
    recorded_at: UtcDateTime
    created_at: UtcDateTime
    poll_after_seconds: int
