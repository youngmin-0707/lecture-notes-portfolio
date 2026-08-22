"""기술 용어 보정 — 프롬프트 바이어싱 + 긴 별칭 우선 치환 (§3.3, T-23, US-13).

2단계로 대응한다:
1. **전사 전 프롬프트 바이어싱** (`build_initial_prompt`) — 용어집의 `term` 목록을
   Whisper `initial_prompt`로 전달해 해당 표기가 나오도록 유도한다.
2. **전사 후 규칙 치환** (`correct_transcript_text`) — `aliases` → `term` 치환. 긴 별칭을
   짧은 별칭보다 먼저 매칭해 과잉 치환(짧은 별칭이 더 긴 다른 용어의 접두부를 잘라먹는 것)을
   막는다. 자세한 이유는 `_correction_pattern()`의 주석 참고.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.glossary import GlossaryTerm


def fetch_applicable_terms(db: DBSession, course: str | None) -> list[GlossaryTerm]:
    """전역(`course=null`) 용어 + (지정 시) 해당 과목 전용 용어를 함께 반환한다."""
    stmt = select(GlossaryTerm)
    if course is not None:
        stmt = stmt.where((GlossaryTerm.course == course) | (GlossaryTerm.course.is_(None)))
    else:
        stmt = stmt.where(GlossaryTerm.course.is_(None))
    return list(db.execute(stmt).scalars().all())


def build_initial_prompt(terms: Sequence[GlossaryTerm]) -> str | None:
    """용어집 `term` 목록으로 Whisper `initial_prompt`를 만든다.

    빈 용어집이면 바이어싱할 게 없으므로 `None`을 반환한다 (provider가 프롬프트 없이
    전사하도록).
    """
    unique_terms = sorted({t.term for t in terms})
    if not unique_terms:
        return None
    return ", ".join(unique_terms)


def _correction_pattern(aliases_to_term: dict[str, str]) -> re.Pattern[str] | None:
    if not aliases_to_term:
        return None
    # 긴 별칭이 짧은 별칭보다 먼저 시도되도록 정렬한다 (§3.3 "긴 별칭이 짧은 별칭보다 우선
    # 매칭") — 같은 시작 위치에서 정규식 대안(|)은 왼쪽부터 순서대로 시도되므로, 이 순서가
    # 곧 "긴 별칭 우선 매칭"이 된다. 예: "포스트그레스큐엘"과 "포스트그레"가 둘 다 등록돼
    # 있으면 전자를 먼저 시도해 "포스트그레"가 그 접두부만 잘라먹지 않게 한다.
    #
    # 영어식 `\b` 단어 경계는 쓰지 않는다 — 한국어는 조사가 공백 없이 명사에 바로 붙는다
    # (예: "자바는", "자바가"). `\b`를 걸면 그런 정상적인 발생조차 매칭에 실패한다. 대신
    # "긴 별칭 우선" 정렬 자체가 §3.3이 실제로 우려하는 과잉 치환(짧은 별칭이 더 긴, 서로
    # 다른 용어의 접두부를 잘라먹는 것)을 이미 막아준다.
    ordered_aliases = sorted(aliases_to_term, key=len, reverse=True)
    alternation = "|".join(re.escape(alias) for alias in ordered_aliases)
    return re.compile(alternation)


def correct_transcript_text(text: str, terms: Sequence[GlossaryTerm]) -> str:
    """`aliases` → `term` 경계 안전 치환을 적용한 보정본을 반환한다 (원본은 호출부가 별도 보존)."""
    aliases_to_term: dict[str, str] = {}
    for term in terms:
        for alias in term.aliases:
            if alias and alias not in aliases_to_term:
                aliases_to_term[alias] = term.term

    pattern = _correction_pattern(aliases_to_term)
    if pattern is None:
        return text

    return pattern.sub(lambda m: aliases_to_term[m.group(0)], text)
