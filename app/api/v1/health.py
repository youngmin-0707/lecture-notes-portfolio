"""환경 점검 `/health` (§5.3⑫, T-28).

**하나라도 실패해도 HTTP는 항상 200이다** — 점검 결과를 조회하는 요청 자체는 성공했기
때문이다(§5.3 다른 엔드포인트들과 동일한 설계 원칙, 예: FAILED 세션 조회도 200). 대신
`status` 필드가 `"ok"`/`"degraded"`로 결과를 표현한다.

API 키(`GEMINI_API_KEY`/`GROQ_API_KEY`)는 **설정 여부만** 노출하고 값 자체는 절대
응답에 담지 않는다(§3.4, §6 보안) — `pydantic.SecretStr`이라 실수로 넣어도 `"**********"`만
직렬화되지만, 애초에 값을 참조하지 않는다.

무거운 모델을 로딩해 점검하지 않는다(§2.2 "무거운 모델 로딩은 첫 사용 시점에 지연 로딩") —
STT는 캐시 디렉토리 존재 여부만 저비용으로 확인하고, LLM은 Ollama 데몬에 짧은 타임아웃으로
핑(`/api/tags`)만 보낸다. 실제 생성 요청은 보내지 않는다.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.fs import ensure_private_dir
from app.db.session import get_db
from app.schemas.health import (
    DatabaseCheck,
    DiskFreeBytesCheck,
    HealthChecks,
    HealthResponse,
    LlmCheck,
    SttCheck,
)

logger = logging.getLogger("app.api.v1.health")

router = APIRouter()

# LLM 데몬 핑 전용 타임아웃 — 실제 생성 요청(OLLAMA_TIMEOUT_SECONDS, 수 분)과는 별개로,
# /health는 사용자가 기다리는 진단 요청이므로 짧게 끊는다.
LLM_PING_TIMEOUT_SECONDS = 2.0


def _check_database(db: DBSession) -> DatabaseCheck:
    try:
        db.execute(text("SELECT 1"))
        return DatabaseCheck(ok=True)
    except Exception:  # noqa: BLE001 — 어떤 DB 오류든 "점검 실패"로 취급한다.
        logger.exception("health check: database query failed")
        return DatabaseCheck(ok=False)


def _check_disk_free_bytes() -> DiskFreeBytesCheck:
    try:
        storage_dir = ensure_private_dir(settings.AUDIO_STORAGE_DIR)
        free_bytes = shutil.disk_usage(storage_dir).free
    except OSError:
        logger.exception("health check: disk usage lookup failed")
        return DiskFreeBytesCheck(ok=False, value=0)
    return DiskFreeBytesCheck(ok=free_bytes >= settings.MIN_DISK_FREE_BYTES, value=free_bytes)


def _stt_model_cached(model_cache_dir: str, model_name: str) -> bool:
    """모델을 로드하지 않고 캐시 디렉토리에 그 이름이 들어간 항목이 있는지만 본다.

    `faster-whisper`(huggingface_hub 캐시 규약)는 `models--<org>--faster-whisper-<model>`
    형태로 저장하므로, 모델명이 디렉토리 이름의 부분 문자열로 들어있는지 보는 것으로 충분하다.
    """
    cache_dir = Path(model_cache_dir)
    if not cache_dir.is_dir():
        return False
    needle = model_name.lower()
    try:
        return any(needle in entry.name.lower() for entry in cache_dir.iterdir())
    except OSError:
        return False


def _check_stt() -> SttCheck:
    model_cached = _stt_model_cached(settings.MODEL_CACHE_DIR, settings.STT_MODEL)
    return SttCheck(
        # 캐시가 안 됐어도 첫 사용 시 자동 다운로드되므로(§3.2) "설정 자체는 유효함"을 의미하는
        # ok=True를 유지한다 — modelCached로 "아직 안 받았을 뿐"임을 구분해서 보여준다.
        ok=True,
        provider=settings.STT_PROVIDER,
        model=settings.STT_MODEL,
        model_cached=model_cached,
    )


def _check_llm() -> LlmCheck:
    provider = settings.LLM_PROVIDER

    if provider == "ollama":
        model = settings.LLM_MODEL
        configured = True
        reachable = False
        try:
            response = httpx.get(
                f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags",
                timeout=LLM_PING_TIMEOUT_SECONDS,
            )
            reachable = response.status_code < 500
        except httpx.HTTPError:
            reachable = False
        return LlmCheck(
            ok=configured and reachable,
            provider=provider,
            model=model,
            configured=configured,
            reachable=reachable,
        )

    if provider == "openai":
        # 클라우드 API — 실제 호출은 쿼터를 소모하므로 /health에서 시도하지 않고 키 존재
        # 여부로만 판단한다(Ollama의 `/api/tags` 핑과 대칭이지만, 값 자체는 노출하지 않는다).
        configured = settings.OPENAI_API_KEY is not None
        return LlmCheck(
            ok=configured,
            provider=provider,
            model=settings.OPENAI_MODEL,
            configured=configured,
            reachable=None,
        )

    # 무료 티어 어댑터(T-29, 선택 구현) 등 그 외 provider는 API 키 존재 여부로만 판단한다 —
    # 실제 호출은 쿼터를 소모하므로 /health에서 시도하지 않는다.
    configured = bool(settings.GEMINI_API_KEY or settings.GROQ_API_KEY)
    return LlmCheck(
        ok=configured,
        provider=provider,
        model=settings.LLM_MODEL,
        configured=configured,
        reachable=None,
    )


@router.get("/health", response_model=HealthResponse)
def health(db: Annotated[DBSession, Depends(get_db, scope="function")]) -> HealthResponse:
    database = _check_database(db)
    disk_free_bytes = _check_disk_free_bytes()
    stt = _check_stt()
    llm = _check_llm()

    all_ok = database.ok and disk_free_bytes.ok and stt.ok and llm.ok

    return HealthResponse(
        status="ok" if all_ok else "degraded",
        checks=HealthChecks(
            database=database,
            disk_free_bytes=disk_free_bytes,
            stt=stt,
            llm=llm,
            # §3.7: 로컬 STT + 로컬 LLM일 때만 "오프라인 모드"다.
            offline_mode=(
                settings.STT_PROVIDER == "local_whisper" and settings.LLM_PROVIDER == "ollama"
            ),
            bind_host=settings.BIND_HOST,
        ),
    )
