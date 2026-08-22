"""용어집 보정 유틸 단위 테스트 (T-23, §3.3, US-13)."""

from __future__ import annotations

from app.glossary.correction import (
    build_initial_prompt,
    correct_transcript_text,
    fetch_applicable_terms,
)
from app.models.glossary import GlossaryTerm


class TestBuildInitialPrompt:
    def test_empty_terms_returns_none(self) -> None:
        assert build_initial_prompt([]) is None

    def test_joins_unique_sorted_terms(self) -> None:
        terms = [
            GlossaryTerm(term="PostgreSQL", aliases=["포스트그레"], course=None),
            GlossaryTerm(term="Docker", aliases=["도커"], course=None),
        ]
        prompt = build_initial_prompt(terms)
        assert prompt is not None
        assert "PostgreSQL" in prompt
        assert "Docker" in prompt

    def test_duplicate_term_names_deduplicated(self) -> None:
        terms = [
            GlossaryTerm(term="PostgreSQL", aliases=["포스트그레"], course=None),
            GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘"], course="자료구조"),
        ]
        prompt = build_initial_prompt(terms)
        assert prompt.count("PostgreSQL") == 1


class TestCorrectTranscriptText:
    def test_no_terms_returns_text_unchanged(self) -> None:
        assert correct_transcript_text("포스트그레스큐엘에서", []) == "포스트그레스큐엘에서"

    def test_no_matching_alias_returns_text_unchanged(self) -> None:
        terms = [GlossaryTerm(term="Docker", aliases=["도커"], course=None)]
        text = "오늘은 이진 탐색 트리를 배웠습니다"
        assert correct_transcript_text(text, terms) == text

    def test_replaces_alias_with_canonical_term(self) -> None:
        terms = [
            GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘", "포스트그레"], course=None)
        ]
        result = correct_transcript_text("포스트그레스큐엘에서 조인을 하면", terms)
        assert result == "PostgreSQL에서 조인을 하면"

    def test_replaces_multiple_occurrences_and_terms(self) -> None:
        terms = [
            GlossaryTerm(term="Docker", aliases=["도커"], course=None),
            GlossaryTerm(term="Kubernetes", aliases=["쿠버네티스"], course=None),
        ]
        result = correct_transcript_text("도커와 쿠버네티스, 그리고 다시 도커", terms)
        assert result == "Docker와 Kubernetes, 그리고 다시 Docker"

    def test_original_text_untouched_by_correction(self) -> None:
        """원본은 별도로 보존되어야 한다 — 이 함수는 새 문자열만 반환하고 원본을 바꾸지 않는다."""
        terms = [GlossaryTerm(term="Docker", aliases=["도커"], course=None)]
        original = "도커 사용법"
        result = correct_transcript_text(original, terms)
        assert original == "도커 사용법"
        assert result == "Docker 사용법"


class TestFetchApplicableTerms:
    def test_no_course_returns_only_global_terms(self, db_session) -> None:
        db_session.add_all(
            [
                GlossaryTerm(term="전역", aliases=[], course=None),
                GlossaryTerm(term="과목전용", aliases=[], course="자료구조"),
            ]
        )
        db_session.flush()

        terms = fetch_applicable_terms(db_session, None)

        assert {t.term for t in terms} == {"전역"}

    def test_course_returns_global_and_course_specific_terms(self, db_session) -> None:
        db_session.add_all(
            [
                GlossaryTerm(term="전역", aliases=[], course=None),
                GlossaryTerm(term="자료구조전용", aliases=[], course="자료구조"),
                GlossaryTerm(term="네트워크전용", aliases=[], course="네트워크"),
            ]
        )
        db_session.flush()

        terms = fetch_applicable_terms(db_session, "자료구조")

        assert {t.term for t in terms} == {"전역", "자료구조전용"}
