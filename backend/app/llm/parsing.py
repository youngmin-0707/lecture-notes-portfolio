"""LLM JSON 응답 파싱 + 마크다운 렌더링 (§3.4, T-16, US-05; 2026-08-29 개정).

`parse_summary_response()`는 형식이 어긋난 응답에 대해 항상 `ValueError`를 던진다.
호출부(`app/llm/summarizer.py`)가 이를 "형식 위반 → 1회 재요청" 신호로 사용한다.

`render_markdown()`은 파싱된 데이터로부터 마크다운을 만들어 낸다. "## 한 줄 요약"과
"## 핵심 주제"만 결정론적으로 조립하고(그 아래에 있어야 프리뷰 추출 로직이 계속 동작한다 —
`app/api/v1/sessions.py`의 `_extract_summary_preview`), 본문은 LLM이 쓴 자유형식
마크다운(`detailed_notes`)을 그대로 붙여넣는다. ("## 복습 키워드" 섹션은 사용률이 낮아
2026-09-01부로 제거 — 앞으로 생성되는 요약부터 적용, 과거 요약은 그대로 둔다.)
"""

from __future__ import annotations

import json
import re

from app.llm.schema import ParsedSummary, SummaryKeyPoint

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
    keywords = _parse_keywords(data.get("keywords", []))
    detailed_notes = _require_str(data.get("detailedNotes"), "detailedNotes")
    suggested_title = _require_str(data.get("suggestedTitle"), "suggestedTitle")

    return ParsedSummary(
        one_line_summary=one_line_summary,
        key_points=key_points,
        keywords=keywords,
        detailed_notes=detailed_notes,
        suggested_title=suggested_title,
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
    """ "## 한 줄 요약" + "## 핵심 주제"는 결정론적으로, 본문은 LLM의 자유형식 마크다운
    (`detailed_notes`)을 그대로 붙인다.

    "## 복습 키워드" 섹션은 사용률이 낮아 2026-09-01부로 제거했다 — 앞으로 생성되는 요약부터
    적용되며, 이미 저장된 과거 요약의 `content_markdown`(DB)은 그대로 둔다.
    """
    lines: list[str] = ["## 한 줄 요약", parsed.one_line_summary.strip(), "", "## 핵심 주제"]

    if parsed.key_points:
        for point in parsed.key_points:
            ts = _format_timestamp(point.at_seconds)
            prefix = f"- [{ts}] " if ts is not None else "- "
            lines.append(f"{prefix}{point.text}")
    else:
        lines.append("없음")

    lines += ["", parsed.detailed_notes.strip()]

    return "\n".join(lines)


_ONE_LINE_SUMMARY_MARKER = "## 한 줄 요약\n"


def extract_one_line_summary(content_markdown: str) -> str:
    """`content_markdown`에서 "## 한 줄 요약" 섹션 본문만 뽑아낸다.

    `render_markdown()`이 이 섹션을 항상 맨 앞에 결정론적으로 넣으므로(위 참고) 문자열
    탐색만으로 안전하게 뽑을 수 있다. 목록 미리보기(`app/api/v1/sessions.py`의
    `_extract_summary_preview`)와 요약 수정(2026-09-14, `update_summary`)이 공유해서 쓴다
    — 사용자가 본문만 고치고 한 줄 요약은 그대로 둘 때, 현재 값을 다시 물어보지 않고 이
    함수로 읽어와 `content_markdown` 재조립에 쓴다.
    """
    start = content_markdown.find(_ONE_LINE_SUMMARY_MARKER)
    if start == -1:
        return content_markdown.strip()
    start += len(_ONE_LINE_SUMMARY_MARKER)
    end = content_markdown.find("\n##", start)
    text = content_markdown[start:] if end == -1 else content_markdown[start:end]
    return text.strip()
