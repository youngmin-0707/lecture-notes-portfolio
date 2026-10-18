"""전문 검색 API (§3.5, §5.3⑨, T-26, US-15).

1차 구현은 DB `LIKE` 기반 단순 검색이다 (§3.5) — 세션 수가 수백 건 규모인 개인 도구에는
이걸로 충분하고, 처음부터 FTS를 넣는 건 이 규모에서 조기 최적화다(§3.5, F-6에서 재검토).

전사는 **보정본** 기준으로 찾는다는 원칙(§3.5)을 지키기 위해, SQL `LIKE`로는 저비용 후보
세션만 추려내고(`text_corrected`/`text_raw` 어느 쪽이든 매칭되면 후보), 실제 스니펫·타임스탬프는
후보 세션의 세그먼트에 T-23 용어 보정을 적용한 뒤 파이썬에서 찾는다 — 저장된
`transcript_segments.text`는 원본 그대로이므로(T-23 결정) 그렇게 하지 않으면 보정된 표기로
검색해도 원문 표기 세그먼트를 못 찾을 수 있다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from app.db.session import get_db
from app.glossary.correction import correct_transcript_text, fetch_applicable_terms
from app.models.glossary import GlossaryTerm
from app.models.session import Session as SessionModel
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.schemas.search import SearchResponse, SearchResultResponse

router = APIRouter(tags=["search"])

SNIPPET_CONTEXT_CHARS = 40


def _build_snippet(
    text: str, query_lower: str, *, context_chars: int = SNIPPET_CONTEXT_CHARS
) -> str | None:
    """`text`에서 `query_lower`가 처음 나오는 위치 주변을 잘라 스니펫을 만든다.

    매칭이 없으면 `None`을 반환한다(호출부가 "이 텍스트에는 실제로 없었다"를 구분할 수 있게).
    """
    idx = text.lower().find(query_lower)
    if idx == -1:
        return None

    start = max(idx - context_chars, 0)
    end = min(idx + len(query_lower) + context_chars, len(text))
    snippet = text[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _find_transcript_match(
    transcript: Transcript, query_lower: str, glossary_terms: list[GlossaryTerm]
) -> tuple[str, float | None] | None:
    """전사에서 스니펫 + 타임스탬프를 찾는다. 세그먼트별로 보정 후 검사한다."""
    for segment in transcript.segments:
        corrected = correct_transcript_text(segment.text, glossary_terms)
        snippet = _build_snippet(corrected, query_lower)
        if snippet is not None:
            return snippet, segment.start_seconds

    # 드문 폴백: 세그먼트 하나에는 없지만(경계에 걸침 등) 이어붙인 보정본 전체에는 있는 경우.
    full_text = transcript.text_corrected or transcript.text_raw
    snippet = _build_snippet(full_text, query_lower)
    if snippet is not None:
        return snippet, None
    return None


def _find_summary_match(summary: Summary, query_lower: str) -> tuple[str, float | None] | None:
    snippet = _build_snippet(summary.content_markdown, query_lower)
    if snippet is None:
        return None

    at_seconds = None
    for key_point in summary.key_points:
        text = key_point.get("text", "")
        if query_lower in text.lower():
            at_seconds = key_point.get("atSeconds")
            break
    return snippet, at_seconds


@router.get("/search", response_model=SearchResponse)
def search(
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    q: Annotated[str, Query(min_length=2)],
    course: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    """전사·요약 전문 검색 (§5.3⑨, US-15)."""
    query_lower = q.lower()
    like_pattern = f"%{query_lower}%"

    session_filters = []
    if course is not None:
        session_filters.append(SessionModel.course == course)

    glossary_cache: dict[str | None, list[GlossaryTerm]] = {}

    def _terms_for(course_value: str | None) -> list[GlossaryTerm]:
        if course_value not in glossary_cache:
            glossary_cache[course_value] = fetch_applicable_terms(db, course_value)
        return glossary_cache[course_value]

    results: list[SearchResultResponse] = []

    # --- 전사 매칭 후보 ---
    transcript_candidates = (
        db.execute(
            select(Transcript)
            .join(SessionModel, Transcript.session_id == SessionModel.id)
            .where(
                *session_filters,
                (func.lower(Transcript.text_corrected).like(like_pattern))
                | (func.lower(Transcript.text_raw).like(like_pattern)),
            )
        )
        .scalars()
        .all()
    )
    for transcript in transcript_candidates:
        session = transcript.session
        match = _find_transcript_match(transcript, query_lower, _terms_for(session.course))
        if match is None:
            continue
        snippet, at_seconds = match
        results.append(
            SearchResultResponse(
                session_id=session.id,
                title=session.title,
                course=session.course,
                recorded_at=session.recorded_at,
                matched_in="TRANSCRIPT",
                snippet=snippet,
                at_seconds=at_seconds,
            )
        )

    # --- 요약 매칭 후보 (세션당 최신 요약만 대상) ---
    # "최신 요약"인지 먼저 정해야 한다 — WHERE에 본문 매칭 조건을 같이 넣으면, 최신 요약은
    # 매칭 안 됐지만 더 예전 요약이 우연히 매칭된 경우 그 예전 요약이 "유일한 후보"가 되어
    # 잘못 "최신"으로 취급된다. 그래서 매칭 여부와 무관하게 세션당 최신 요약 1건을 먼저 뽑고,
    # 그 본문이 검색어와 매칭되는지는 아래에서 파이썬으로 따로 확인한다.
    latest_summary_by_session: dict[str, Summary] = {}
    for summary in (
        db.execute(
            select(Summary)
            .join(SessionModel, Summary.session_id == SessionModel.id)
            .where(*session_filters)
            .order_by(Summary.session_id, Summary.created_at.desc())
        )
        .scalars()
        .all()
    ):
        latest_summary_by_session.setdefault(summary.session_id, summary)

    for summary in latest_summary_by_session.values():
        match = _find_summary_match(summary, query_lower)
        if match is None:
            continue
        snippet, at_seconds = match
        session = summary.session
        results.append(
            SearchResultResponse(
                session_id=session.id,
                title=session.title,
                course=session.course,
                recorded_at=session.recorded_at,
                matched_in="SUMMARY",
                snippet=snippet,
                at_seconds=at_seconds,
            )
        )

    results.sort(key=lambda r: r.recorded_at, reverse=True)

    return SearchResponse(query=q, results=results[:limit], total_count=len(results))
