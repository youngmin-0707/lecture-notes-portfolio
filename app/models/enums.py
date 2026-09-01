"""애플리케이션 레벨 Enum (§2.3 dialect 중립 규칙: 네이티브 ENUM 대신 String + 검증).

DB 컬럼 타입은 항상 `String(20)`이고, 저장 전 애플리케이션에서 이 Enum 값으로 검증한다.
"""

from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    """세션 상태 전이 (§2.4)."""

    UPLOADED = "UPLOADED"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBED = "TRANSCRIBED"
    SUMMARIZING = "SUMMARIZING"
    DONE = "DONE"
    FAILED = "FAILED"


class SessionSource(str, Enum):
    """세션 입력 방식 (§2.3 `sessions.source`)."""

    UPLOAD = "UPLOAD"
    RECORD = "RECORD"


class QuizStatus(str, Enum):
    """복습 문제(퀴즈) 생성 상태 (2026-09-01 신규, §2.4의 세션 상태와는 별개 축)."""

    GENERATING = "GENERATING"
    DONE = "DONE"
    FAILED = "FAILED"
