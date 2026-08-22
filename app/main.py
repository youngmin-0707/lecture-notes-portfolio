"""FastAPI 애플리케이션 엔트리포인트."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.sessions import router as sessions_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.db.session import SessionLocal
from app.pipeline.recovery import sweep_interrupted_sessions

logger = logging.getLogger("app.main")


# 개인용 로컬 도구다 — 인증이 없으므로 127.0.0.1 바인딩이 유일한 방어선이다 (§3.7, §6, US-11).
# `uvicorn app.main:app --host 0.0.0.0`처럼 어떤 방식으로 기동하더라도 이 모듈을 import하는
# 순간 검증되므로 우회할 수 없다.
def validate_bind_host(host: str) -> None:
    if host == "0.0.0.0":  # noqa: S104
        raise SystemExit(
            "BIND_HOST=0.0.0.0는 허용되지 않습니다. 이 도구는 인증이 없는 개인용 로컬 앱이므로 "
            "반드시 127.0.0.1(로컬호스트)에만 바인딩해야 합니다. 같은 네트워크의 다른 사용자가 "
            "강의 녹음·전사에 접근할 수 있게 되는 것을 막기 위한 안전장치입니다."
        )


validate_bind_host(settings.BIND_HOST)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """서버 기동 시 비정상 종료 복구 스윕을 1회 실행한다 (T-20, §3.6, US-10).

    `BackgroundTasks`는 서버가 재시작되면 진행 중이던 작업을 그대로 잃는다. `TRANSCRIBING`/
    `SUMMARIZING` 상태로 남아있는 세션을 전부 `FAILED(error_code="INTERRUPTED")`로 전이시켜,
    사용자가 재실행할 수 있는 상태로 되돌린다.
    """
    db = SessionLocal()
    try:
        swept_ids = sweep_interrupted_sessions(db)
        db.commit()
        if swept_ids:
            logger.warning(
                "startup recovery sweep: %d session(s) marked FAILED(INTERRUPTED): %s",
                len(swept_ids),
                swept_ids,
            )
    except Exception:
        db.rollback()
        logger.exception("startup recovery sweep failed")
    finally:
        db.close()

    yield


app = FastAPI(title="API", version="1.0.0", lifespan=lifespan)

# CORS: http://127.0.0.1:* , http://localhost:* 만 허용한다 (§3.7).
_ALLOWED_ORIGIN_REGEX = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX.pattern,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """모든 응답에 requestId를 부여한다 (요구사항 §5.1, §6 관측성)."""
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


register_exception_handlers(app)

app.include_router(sessions_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
