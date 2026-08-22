"""용어집 Pydantic 요청/응답 스키마 (§5.3 ⑩, T-22)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelModel


class GlossaryTermCreate(CamelModel):
    """POST /api/v1/glossary 요청 바디."""

    term: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list)
    course: str | None = Field(default=None, max_length=100)


class GlossaryTermResponse(CamelModel):
    """용어집 항목 1건 응답."""

    id: int
    term: str
    aliases: list[str]
    course: str | None


class GlossaryListResponse(CamelModel):
    """GET /api/v1/glossary 응답."""

    items: list[GlossaryTermResponse]
