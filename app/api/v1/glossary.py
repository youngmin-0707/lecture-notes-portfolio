"""용어집 API (§5.3 ⑩, T-22)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.errors import AppError
from app.db.session import get_db
from app.models.glossary import GlossaryTerm
from app.schemas.glossary import GlossaryListResponse, GlossaryTermCreate, GlossaryTermResponse

router = APIRouter(tags=["glossary"])


def _to_response(term: GlossaryTerm) -> GlossaryTermResponse:
    return GlossaryTermResponse(
        id=term.id, term=term.term, aliases=list(term.aliases), course=term.course
    )


@router.get("/glossary", response_model=GlossaryListResponse)
def list_glossary_terms(
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    course: str | None = None,
) -> GlossaryListResponse:
    """용어집 조회 (§5.3 ⑩).

    `course`를 지정하면 해당 과목 전용 + 전역(`course=null`) 용어를 함께 반환한다.
    """
    stmt = select(GlossaryTerm).order_by(GlossaryTerm.term)
    if course is not None:
        stmt = stmt.where((GlossaryTerm.course == course) | (GlossaryTerm.course.is_(None)))
    terms = db.execute(stmt).scalars().all()
    return GlossaryListResponse(items=[_to_response(t) for t in terms])


@router.post("/glossary", status_code=201, response_model=GlossaryTermResponse)
def create_glossary_term(
    body: GlossaryTermCreate,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> GlossaryTermResponse:
    """용어집 항목 추가 (§5.3 ⑩)."""
    term = GlossaryTerm(term=body.term, aliases=body.aliases, course=body.course)
    db.add(term)
    db.flush()
    db.refresh(term)
    return _to_response(term)


@router.delete("/glossary/{term_id}", status_code=204)
def delete_glossary_term(
    term_id: int,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> None:
    """용어집 항목 삭제 (§5.3 ⑩). 없는 id는 `NOT_FOUND`(404)."""
    term = db.get(GlossaryTerm, term_id)
    if term is None:
        raise AppError("NOT_FOUND")
    db.delete(term)
    db.flush()
