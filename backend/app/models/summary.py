"""`summaries` 테이블 ORM 모델 (§2.3).

세션당 N건을 허용해 다른 모델로 재요약 후 비교할 수 있게 한다 (§2.3, US-17).

`detailed_notes_markdown`은 2026-08-29에 추가됐다 — LLM이 자유형식으로 쓴 본문 마크다운을
그대로 담는다(§3.4 개정, `app/llm/schema.py` 참고). `concepts`/`code_snippets`/
`action_items` 컬럼은 그 이전 고정 6섹션 방식의 유산으로, 과거 요약 데이터 호환을 위해
스키마는 남겨뒀지만 이후 생성되는 요약에는 항상 빈 배열만 채워진다.
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


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    concepts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    code_snippets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    action_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    detailed_notes_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    session = relationship("Session", back_populates="summaries")
