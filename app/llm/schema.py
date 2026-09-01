"""요약 고정 출력 스키마 (§3.4, T-16; 2026-08-29 자유형식 본문 도입으로 개정).

LLM 원문 응답(JSON)을 파싱한 결과를 담는 불변 dataclass들. 예전에는 개념/코드/과제를 각각
고정 필드로 강제했지만, 실사용 비교 결과 그 방식이 설명을 "용어: 한 줄 정의"로 뭉뚱그리게
만든다는 게 확인되어 `detailed_notes`(자유형식 마크다운 본문) 하나로 대체했다 — 강의마다
다른 섹션 구성(예: "강사 당부사항")이 필요할 수 있어 고정 필드로는 표현이 안 됐다.
`key_points`(타임스탬프 점프용)와 `keywords`(짧은 태그)만 계속 구조화된 필드로 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SummaryKeyPoint:
    """`## 핵심 주제` 섹션의 항목. 원문 대조를 위해 타임스탬프를 병기한다 (§3.4 환각 방어)."""

    text: str
    at_seconds: float | None = None


@dataclass(frozen=True)
class ParsedSummary:
    """LLM 응답을 파싱한 결과."""

    one_line_summary: str
    key_points: list[SummaryKeyPoint] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    detailed_notes: str = ""
    # 세션 목록에서 강의를 구별하기 위한 제안 제목 (2026-08-30). 사용자가 제목을 직접 바꾼
    # 적이 없을 때만(`session.title_customized is False`) 실제 세션 제목에 반영된다.
    suggested_title: str = ""
