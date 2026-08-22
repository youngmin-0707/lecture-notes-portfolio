"""공통 에러 응답 포맷 (요구사항 §5.1) 및 전역 예외 핸들러."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

# 에러코드별 HTTP status + 기본 한국어 메시지 (요구사항 §5.1 전체 17개 코드).
# `NOT_FOUND`/`HTTP_ERROR`는 §5.1에 없는 코드지만, 라우트 미존재(404)나 그 외 Starlette
# HTTPException(예: 405)을 감쌀 표준 폴백으로 둔다.
CODE_STATUS: dict[str, int] = {
    "VALIDATION_ERROR": 400,
    "INVALID_AUDIO_FILE": 400,
    "AUDIO_TOO_SHORT": 400,
    "AUDIO_TOO_LONG": 400,
    "SESSION_NOT_FOUND": 404,
    "INVALID_SESSION_STATE": 409,
    "TRANSCRIPT_NOT_READY": 409,
    "FILE_TOO_LARGE": 413,
    "UNSUPPORTED_AUDIO_FORMAT": 415,
    "STT_MODEL_UNAVAILABLE": 503,
    "STT_FAILED": 500,
    "LLM_NOT_CONFIGURED": 503,
    "LLM_QUOTA_EXCEEDED": 429,
    "LLM_INVALID_RESPONSE": 502,
    "LLM_FAILED": 502,
    "INSUFFICIENT_DISK_SPACE": 507,
    "INTERNAL_ERROR": 500,
    "NOT_FOUND": 404,
    "HTTP_ERROR": 400,
}

CODE_MESSAGES: dict[str, str] = {
    "VALIDATION_ERROR": "입력값이 올바르지 않습니다.",
    "INVALID_AUDIO_FILE": "오디오 파일을 읽을 수 없습니다.",
    "AUDIO_TOO_SHORT": "오디오가 너무 짧습니다.",
    "AUDIO_TOO_LONG": "오디오 길이가 최대 240분을 초과합니다.",
    "SESSION_NOT_FOUND": "세션을 찾을 수 없습니다.",
    "INVALID_SESSION_STATE": "현재 상태에서는 수행할 수 없습니다.",
    "TRANSCRIPT_NOT_READY": "전사가 아직 완료되지 않았습니다.",
    "FILE_TOO_LARGE": "파일 크기가 최대 500MB를 초과합니다.",
    "UNSUPPORTED_AUDIO_FORMAT": "지원하지 않는 오디오 형식입니다.",
    "STT_MODEL_UNAVAILABLE": "음성 인식 모델을 준비할 수 없습니다.",
    "STT_FAILED": "전사에 실패했습니다.",
    "LLM_NOT_CONFIGURED": "요약 엔진이 설정되지 않았습니다.",
    "LLM_QUOTA_EXCEEDED": "요약 API 사용 한도를 초과했습니다.",
    "LLM_INVALID_RESPONSE": "요약 결과 형식이 올바르지 않습니다.",
    "LLM_FAILED": "요약 생성에 실패했습니다.",
    "INSUFFICIENT_DISK_SPACE": "디스크 여유 공간이 부족합니다.",
    "INTERNAL_ERROR": "서버 오류가 발생했습니다.",
    "NOT_FOUND": "요청한 리소스를 찾을 수 없습니다.",
    "HTTP_ERROR": "요청을 처리할 수 없습니다.",
}

# RequestValidationError(422)를 400 VALIDATION_ERROR로 변환할 때 field별 reason에 붙는 메시지.
REASON_MESSAGES: dict[str, str] = {
    "REQUIRED": "필수 입력값입니다.",
    "INVALID_VALUE": "입력값이 올바르지 않습니다.",
}


class AppError(Exception):
    """의도된 비즈니스/검증 예외.

    `code`는 §5.1의 17개 에러 코드 중 하나여야 하며, HTTP status는 `CODE_STATUS`에서
    자동으로 결정된다 (호출부에서 상태 코드를 잘못 지정해 명세와 어긋나는 사고를 막는다).
    """

    def __init__(
        self,
        code: str,
        message: str | None = None,
        details: list[dict[str, Any]] | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.status_code = status_code or CODE_STATUS.get(code, 500)
        self.message = message or CODE_MESSAGES.get(code, "요청을 처리할 수 없습니다.")
        self.details = details or []
        # §3.4 Provider 정책: 429/5xx/타임아웃만 재시도 대상이다. LLM Provider(T-17)가 이 플래그로
        # 표시하면, 요약 오케스트레이션(T-18)이 지수 백오프 재시도 여부를 판단한다. 기본값은 False라
        # 기존 호출부(STT 등)의 동작에는 영향이 없다.
        self.retryable = retryable
        super().__init__(self.message)


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id or str(uuid.uuid4())


def _error_body(code: str, message: str, details: list[dict[str, Any]], request_id: str) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details or []},
        "requestId": request_id,
    }


def _reason_from_pydantic_error(err: dict) -> str:
    raw_msg = err.get("msg", "") or ""
    prefix = "Value error, "
    if raw_msg.startswith(prefix):
        return raw_msg[len(prefix) :]
    if err.get("type") == "missing":
        return "REQUIRED"
    return "INVALID_VALUE"


def _field_from_loc(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = []
        for err in exc.errors():
            field = _field_from_loc(tuple(err.get("loc", ())))
            reason = _reason_from_pydantic_error(err)
            details.append(
                {
                    "field": field,
                    "reason": reason,
                    "message": REASON_MESSAGES.get(reason, reason),
                }
            )
        return JSONResponse(
            status_code=400,
            content=_error_body(
                "VALIDATION_ERROR", CODE_MESSAGES["VALIDATION_ERROR"], details, _request_id(request)
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = (
            exc.detail
            if isinstance(exc.detail, str) and exc.detail
            else CODE_MESSAGES.get(code, "요청을 처리할 수 없습니다.")
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, message, [], _request_id(request)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 스택트레이스는 서버 로그로만 남기고 클라이언트에는 노출하지 않는다 (§6 보안).
        logger.exception("Unhandled exception while processing request", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_body(
                "INTERNAL_ERROR", CODE_MESSAGES["INTERNAL_ERROR"], [], _request_id(request)
            ),
        )
