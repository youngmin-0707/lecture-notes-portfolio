"""`quizzes` 테이블 ORM 모델 (2026-09-01, 복습 문제 자동 생성 기능).

세션당 N건을 허용한다 (`summaries`와 동일한 관례, §2.3) — "복습 탭을 열 때마다 새로
생성"이 아니라 최초 생성 후 캐시해두고, 필요하면 재생성 버튼으로 새 행을 하나 더 추가하는
방식이다. API는 항상 최신 1건만 반환한다.

생성은 세션의 요약(`detailed_notes_markdown`)이 이미 있어야 가능하고(§`app/pipeline/quiz.py`
참고), 생성 자체가 LLM 호출 1회를 수반하는 비동기 작업이라 `status`로 진행 상태를
추적한다 — `sessions.status`(§2.4)와는 별개의 축이다: 세션 하나가 DONE이어도 퀴즈는
아직 없을 수도(GENERATING/FAILED/미생성) 있다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.session import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # [{"question": "...", "answer": "..."}, ...] — status=DONE일 때만 채워진다.
    questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    provider_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    session = relationship("Session", back_populates="quizzes")
