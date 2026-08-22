"""모든 ORM 모델을 import해 `Base.metadata`에 등록한다.

`tests/conftest.py`, `alembic/env.py`가 `import app.models`만으로 전체 스키마를
`Base.metadata`에 채우기 위해 의존하는 모듈이다.
"""

from __future__ import annotations

from app.models.enums import SessionSource, SessionStatus
from app.models.glossary import GlossaryTerm
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript, TranscriptSegment

__all__ = [
    "GlossaryTerm",
    "Session",
    "SessionSource",
    "SessionStatus",
    "Summary",
    "Transcript",
    "TranscriptSegment",
]
