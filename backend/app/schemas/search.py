"""전문 검색 Pydantic 응답 스키마 (§5.3⑨, T-26)."""

from __future__ import annotations

from app.schemas.common import CamelModel, UtcDateTime


class SearchResultResponse(CamelModel):
    """`results[]` 항목 하나 — 세션 1건의 매칭 위치 1곳."""

    session_id: str
    title: str
    course: str | None
    recorded_at: UtcDateTime
    matched_in: str
    snippet: str
    at_seconds: float | None = None


class SearchResponse(CamelModel):
    """GET /api/v1/search 응답."""

    query: str
    results: list[SearchResultResponse]
    total_count: int
