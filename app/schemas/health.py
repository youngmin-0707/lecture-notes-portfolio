"""`/health` 응답 Pydantic 스키마 (§5.3⑫, T-28)."""

from __future__ import annotations

from app.schemas.common import CamelModel


class DatabaseCheck(CamelModel):
    ok: bool


class DiskFreeBytesCheck(CamelModel):
    ok: bool
    value: int


class SttCheck(CamelModel):
    ok: bool
    provider: str
    model: str
    model_cached: bool


class LlmCheck(CamelModel):
    ok: bool
    provider: str
    model: str
    configured: bool
    reachable: bool | None = None


class HealthChecks(CamelModel):
    database: DatabaseCheck
    disk_free_bytes: DiskFreeBytesCheck
    stt: SttCheck
    llm: LlmCheck
    offline_mode: bool
    bind_host: str


class HealthResponse(CamelModel):
    status: str
    checks: HealthChecks
