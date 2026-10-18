"""Pydantic 응답 스키마 공통 베이스 (§5.1: 요청/응답 필드 camelCase, 시각은 ISO8601 UTC)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel


def _serialize_utc_z(value: datetime) -> str:
    """UTC-aware datetime을 `...Z` 접미사의 ISO8601 문자열로 직렬화한다."""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[datetime, PlainSerializer(_serialize_utc_z, return_type=str)]


class CamelModel(BaseModel):
    """모든 응답 스키마의 베이스: snake_case 필드명을 camelCase로 직렬화한다."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
