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


class ProgressResponse(CamelModel):
    """§5.3③ "처리 중" 응답의 `progress` 객체."""

    stage: str
    percent: float
    eta_seconds: float | None = None


class TranscriptInfoResponse(CamelModel):
    """§5.3③ 응답에 포함되는 전사 요약 정보 (전문은 ④ 별도 엔드포인트에서 조회)."""

    available: bool
    provider: str | None = None
    provider_model: str | None = None
    character_count: int | None = None
    elapsed_seconds: float | None = None


class SessionDetailResponse(CamelModel):
    """GET /api/v1/sessions/{id} 응답 (§5.3③).

    이번 라운드(그룹 C)에는 요약 기능이 없으므로 `summary`는 항상 `null`이다
    (그룹 D/T-16~T-19에서 채워진다).
    """

    session_id: str
    title: str
    course: str | None
    status: str
    duration_seconds: float | None
    recorded_at: UtcDateTime
    error_code: str | None = None
    error_message: str | None = None
    progress: ProgressResponse | None = None
    poll_after_seconds: int | None = None
    transcript: TranscriptInfoResponse
    summary: dict | None = None


class TranscriptSegmentResponse(CamelModel):
    """§5.3④ `segments[]` 항목."""

    seq: int
    start_seconds: float
    end_seconds: float
    text: str


class TranscriptDetailResponse(CamelModel):
    """GET /api/v1/sessions/{id}/transcript 응답 (§5.3④)."""

    session_id: str
    language: str
    corrected: bool
    text: str
    segments: list[TranscriptSegmentResponse]
