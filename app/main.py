"""FastAPI 애플리케이션 엔트리포인트."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request

from app.core.errors import register_exception_handlers

app = FastAPI(title="API", version="1.0.0")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """모든 응답에 requestId를 부여한다 (요구사항 §5.1, §6 관측성)."""
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


register_exception_handlers(app)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
