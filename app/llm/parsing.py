"""LLM JSON 응답 파싱 + 고정 6섹션 마크다운 렌더링 (§3.4, T-16, US-05).

`parse_summary_response()`는 형식이 어긋난 응답에 대해 항상 `ValueError`를 던진다.
호출부(`app/llm/summarizer.py`)가 이를 "형식 위반 → 1회 재요청" 신호로 사용한다.

`render_markdown()`은 파싱된 구조화 데이터로부터 §3.4의 고정 6섹션 마크다운을 항상 만들어
낸다 — LLM이 마크다운 자체를 쓰게 하지 않으므로, 섹션 누락이나 헤더 표기 오류가 구조적으로
발생할 수 없다. 과제/공지가 없으면(`action_items == []`) 반드시 "없음"을 명시한다 (US-05).
"""

from __future__ import annotations

import json
import re

from app.llm.schema import (
    ParsedSummary,
    SummaryActionItem,
    SummaryCodeSnippet,
    SummaryConcept,
    SummaryKeyPoint,
)

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\n?|\n?```$")


def _strip_code_fence(text: str) -> str:
    """LLM이 지시를 어기고 ```json ... ``` 코드펜스로 감싸는 경우를 관대하게 벗겨낸다."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = _CODE_FENCE_RE.sub("", stripped).strip()
    return stripped


def _require_str(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' 필드는 문자열이어야 합니다.")
    if not allow_empty and not value.strip():
        raise ValueError(f"'{field_name}' 필드가 비어 있습니다.")
    return value


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool은 int의 서브클래스라 명시적으로 배제한다.
        raise ValueError(f"'{field_name}' 필드는 숫자여야 합니다.")
    if isinstance(value, int | float):
        return float(value)
    raise ValueError(f"'{field_name}' 필드는 숫자여야 합니다.")


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' 필드는 문자열이어야 합니다.")
    return value or None


def _parse_key_points(raw: object) -> list[SummaryKeyPoint]:
    if not isinstance(raw, list):
        raise ValueError("'keyPoints' 필드는 배열이어야 합니다.")
    points: list[SummaryKeyPoint] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("'keyPoints' 항목은 객체여야 합니다.")
        if "atSeconds" not in item:
            raise ValueError("'keyPoints' 항목에 'atSeconds' 필드가 없습니다.")
        text = _require_str(item.get("text"), "keyPoints[].text")
        at_seconds = _optional_float(item.get("atSeconds"), "keyPoints[].atSeconds")
        points.append(SummaryKeyPoint(text=text, at_seconds=at_seconds))
    return points


def _parse_concepts(raw: object) -> list[SummaryConcept]:
    if not isinstance(raw, list):
        raise ValueError("'concepts' 필드는 배열이어야 합니다.")
    concepts: list[SummaryConcept] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("'concepts' 항목은 객체여야 합니다.")
        term = _require_str(item.get("term"), "concepts[].term")
        description = _require_str(item.get("description"), "concepts[].description")
        concepts.append(SummaryConcept(term=term, description=description))
    return concepts


def _parse_code_snippets(raw: object) -> list[SummaryCodeSnippet]:
    if not isinstance(raw, list):
        raise ValueError("'codeSnippets' 필드는 배열이어야 합니다.")
    snippets: list[SummaryCodeSnippet] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("'codeSnippets' 항목은 객체여야 합니다.")
        language = _optional_str(item.get("language"), "codeSnippets[].language") or ""
        code = _require_str(item.get("code"), "codeSnippets[].code")
        description = _optional_str(item.get("description"), "codeSnippets[].description") or ""
        snippets.append(SummaryCodeSnippet(language=language, code=code, description=description))
    return snippets


def _parse_action_items(raw: object) -> list[SummaryActionItem]:
    if not isinstance(raw, list):
        raise ValueError("'actionItems' 필드는 배열이어야 합니다.")
    items: list[SummaryActionItem] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("'actionItems' 항목은 객체여야 합니다.")
        text = _require_str(item.get("text"), "actionItems[].text")
        due_date = _optional_str(item.get("dueDate"), "actionItems[].dueDate")
        items.append(SummaryActionItem(text=text, due_date=due_date))
    return items


def _parse_keywords(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("'keywords' 필드는 배열이어야 합니다.")
    keywords: list[str] = []
    for item in raw:
        keywords.append(_require_str(item, "keywords[]"))
    return keywords


def parse_summary_response(raw_text: str) -> ParsedSummary:
    """LLM 원문 응답을 `ParsedSummary`로 파싱한다.

    JSON 파싱 실패, 필수 필드 누락/타입 불일치 등 어떤 형식 위반이든 `ValueError`를 던진다.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("LLM 응답이 비어 있습니다.")

    candidate = _strip_code_fence(raw_text)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"유효한 JSON이 아닙니다: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("응답 최상위는 JSON 객체여야 합니다.")

    one_line_summary = _require_str(data.get("oneLineSummary"), "oneLineSummary")
    key_points = _parse_key_points(data.get("keyPoints", []))
    concepts = _parse_concepts(data.get("concepts", []))
    code_snippets = _parse_code_snippets(data.get("codeSnippets", []))
    action_items = _parse_action_items(data.get("actionItems", []))
    keywords = _parse_keywords(data.get("keywords", []))

    return ParsedSummary(
        one_line_summary=one_line_summary,
        key_points=key_points,
        concepts=concepts,
        code_snippets=code_snippets,
        action_items=action_items,
        keywords=keywords,
    )


def _format_timestamp(seconds: float | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def render_markdown(parsed: ParsedSummary) -> str:
    """§3.4 고정 6섹션 마크다운을 만든다. 6개 헤더는 항상 존재한다 (US-05)."""
    lines: list[str] = ["## 한 줄 요약", parsed.one_line_summary.strip(), "", "## 핵심 주제"]

    if parsed.key_points:
        for point in parsed.key_points:
            ts = _format_timestamp(point.at_seconds)
            prefix = f"- [{ts}] " if ts is not None else "- "
            lines.append(f"{prefix}{point.text}")
    else:
        lines.append("없음")

    lines += ["", "## 개념 정리"]
    if parsed.concepts:
        for concept in parsed.concepts:
            lines.append(f"- **{concept.term}**: {concept.description}")
    else:
        lines.append("없음")

    lines += ["", "## 코드 / 명령어"]
    if parsed.code_snippets:
        for snippet in parsed.code_snippets:
            lines.append(f"```{snippet.language}".rstrip())
            lines.append(snippet.code)
            lines.append("```")
            if snippet.description:
                lines.append(snippet.description)
    else:
        lines.append("없음")

    lines += ["", "## 과제 및 공지"]
    if parsed.action_items:
        for item in parsed.action_items:
            due = f" (마감: {item.due_date})" if item.due_date else ""
            lines.append(f"- {item.text}{due}")
    else:
        lines.append("없음")

    lines += ["", "## 복습 키워드"]
    lines.append(", ".join(parsed.keywords) if parsed.keywords else "없음")

    return "\n".join(lines)
