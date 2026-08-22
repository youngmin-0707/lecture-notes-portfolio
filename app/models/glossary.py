"""`glossary_terms` 테이블 ORM 모델 (§2.3, §3.3).

기술 용어 오인식 보정에 쓰인다: `aliases`(오인식 패턴) → `term`(정식 표기) 치환.
"""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(100), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    course: Mapped[str | None] = mapped_column(String(100), nullable=True)
