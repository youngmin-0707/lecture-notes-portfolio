"""공통 에러 체계 단위 테스트 (T-03, 요구사항 §5.1)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import CODE_MESSAGES, CODE_STATUS, AppError, register_exception_handlers

ALL_CODES = [
    ("VALIDATION_ERROR", 400),
    ("INVALID_AUDIO_FILE", 400),
    ("AUDIO_TOO_SHORT", 400),
    ("AUDIO_TOO_LONG", 400),
    ("SESSION_NOT_FOUND", 404),
    ("INVALID_SESSION_STATE", 409),
    ("TRANSCRIPT_NOT_READY", 409),
    ("FILE_TOO_LARGE", 413),
    ("UNSUPPORTED_AUDIO_FORMAT", 415),
    ("STT_MODEL_UNAVAILABLE", 503),
    ("STT_FAILED", 500),
    ("LLM_NOT_CONFIGURED", 503),
    ("LLM_QUOTA_EXCEEDED", 429),
    ("LLM_INVALID_RESPONSE", 502),
    ("LLM_FAILED", 502),
    ("INSUFFICIENT_DISK_SPACE", 507),
    ("INTERNAL_ERROR", 500),
]


@pytest.fixture()
def error_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom/{code}")
    def boom(code: str) -> None:
        raise AppError(code)

    @app.get("/unexpected")
    def unexpected() -> None:
        raise RuntimeError("stack trace should not leak")

    return app


@pytest.mark.parametrize("code,status", ALL_CODES)
def test_app_error_serializes_with_spec_status(error_app: FastAPI, code: str, status: int) -> None:
    client = TestClient(error_app, raise_server_exceptions=False)
    response = client.get(f"/boom/{code}")

    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"] == CODE_MESSAGES[code]
    assert "requestId" in body


def test_all_17_spec_codes_present() -> None:
    spec_codes = {
        "VALIDATION_ERROR",
        "INVALID_AUDIO_FILE",
        "AUDIO_TOO_SHORT",
        "AUDIO_TOO_LONG",
        "SESSION_NOT_FOUND",
        "INVALID_SESSION_STATE",
        "TRANSCRIPT_NOT_READY",
        "FILE_TOO_LARGE",
        "UNSUPPORTED_AUDIO_FORMAT",
        "STT_MODEL_UNAVAILABLE",
        "STT_FAILED",
        "LLM_NOT_CONFIGURED",
        "LLM_QUOTA_EXCEEDED",
        "LLM_INVALID_RESPONSE",
        "LLM_FAILED",
        "INSUFFICIENT_DISK_SPACE",
        "INTERNAL_ERROR",
    }
    assert spec_codes.issubset(CODE_STATUS.keys())
    assert spec_codes.issubset(CODE_MESSAGES.keys())


def test_unexpected_exception_returns_internal_error_without_leaking_details(
    error_app: FastAPI,
) -> None:
    client = TestClient(error_app, raise_server_exceptions=False)
    response = client.get("/unexpected")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "stack trace" not in response.text
    assert "RuntimeError" not in response.text


def test_no_leftover_signup_project_error_codes() -> None:
    leftover = {
        "EMAIL_ALREADY_EXISTS",
        "NICKNAME_ALREADY_EXISTS",
        "INVALID_EMAIL_FORMAT",
        "INVALID_NICKNAME",
        "INVALID_CREDENTIALS",
        "UNAUTHORIZED",
        "RATE_LIMIT_EXCEEDED",
    }
    assert leftover.isdisjoint(CODE_STATUS.keys())
