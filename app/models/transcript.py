"""`transcripts` / `transcript_segments` 테이블 ORM 모델 (§2.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime as SADateTime
from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.session import utcnow


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Transcript(Base):
    """세션 1건당 최대 1건. 원본(text_raw)과 용어집 보정본(text_corrected)을 모두 보존한다."""

    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    text_raw: Mapped[str] = mapped_column(Text, nullable=False)
    text_corrected: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(100), nullable=False)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        SADateTime(timezone=True), nullable=False, default=utcnow
    )

    session = relationship("Session", back_populates="transcript")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TranscriptSegment.seq",
    )


class TranscriptSegment(Base):
    """전사의 시간 구간 (시작/끝 초 + 텍스트). seq 오름차순, 시작 시각 단조 증가·비중첩."""

    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("transcript_id", "seq", name="uq_transcript_segment_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    transcript = relationship("Transcript", back_populates="segments")
