"""복습 문제(퀴즈) 관련 Pydantic 요청/응답 스키마 (2026-09-01 신규)."""

from __future__ import annotations

from app.schemas.common import CamelModel, UtcDateTime


class CreateQuizRequest(CamelModel):
    """POST /api/v1/sessions/{id}/quiz 요청 바디. 전부 선택."""

    llm_provider: str | None = None


class QuizTriggerResponse(CamelModel):
    """POST /api/v1/sessions/{id}/quiz 응답. 202 Accepted — 즉시 응답, 생성은 백그라운드."""

    session_id: str
    status: str
    poll_after_seconds: int


class QuizQuestionResponse(CamelModel):
    """GET /api/v1/sessions/{id}/quiz 응답의 `questions[]` 항목."""

    question: str
    answer: str


class QuizResponse(CamelModel):
    """GET /api/v1/sessions/{id}/quiz 응답. `status`가 GENERATING이면 `pollAfterSeconds`로
    다시 조회하라는 힌트를 함께 내려준다 (다른 처리 중 응답들과 동일한 관례)."""

    quiz_id: str
    session_id: str
    status: str
    questions: list[QuizQuestionResponse]
    error_code: str | None = None
    error_message: str | None = None
    poll_after_seconds: int | None = None
    created_at: UtcDateTime
