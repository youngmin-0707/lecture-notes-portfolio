"""요약 고정 출력 스키마 (§3.4, T-16).

LLM 원문 응답(JSON)을 파싱한 결과를 담는 불변 dataclass들. `summaries` 테이블의
JSON 컬럼(`key_points`/`concepts`/`code_snippets`/`action_items`/`keywords`)과
`content_markdown`(§3.4 고정 6섹션)에 1:1 대응한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SummaryKeyPoint:
    """`## 핵심 주제` 섹션의 항목. 원문 대조를 위해 타임스탬프를 병기한다 (§3.4 환각 방어)."""

    text: str
    at_seconds: float | None = None


@dataclass(frozen=True)
class SummaryConcept:
    """`## 개념 정리` 섹션의 항목 (용어: 설명)."""

    term: str
    description: str


@dataclass(frozen=True)
class SummaryCodeSnippet:
    """`## 코드 / 명령어` 섹션의 항목."""

    language: str
    code: str
    description: str = ""


@dataclass(frozen=True)
class SummaryActionItem:
    """`## 과제 및 공지` 섹션의 항목."""

    text: str
    due_date: str | None = None


@dataclass(frozen=True)
class ParsedSummary:
    """LLM 응답을 파싱한 결과 — §3.4 고정 6섹션 전체를 담는다."""

    one_line_summary: str
    key_points: list[SummaryKeyPoint] = field(default_factory=list)
    concepts: list[SummaryConcept] = field(default_factory=list)
    code_snippets: list[SummaryCodeSnippet] = field(default_factory=list)
    action_items: list[SummaryActionItem] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
