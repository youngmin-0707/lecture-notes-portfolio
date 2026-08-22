"""SQLAlchemy 선언적 Base. 모든 ORM 모델은 이 Base를 상속한다."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
