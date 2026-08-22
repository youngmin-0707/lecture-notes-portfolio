"""요약 프롬프트 구성 (§3.4, T-16).

LLM에게 항상 **엄격한 JSON**으로만 응답하도록 강제한다. 마크다운 6섹션(`## 한 줄 요약` 등)
문자열 자체는 LLM이 직접 쓰지 않는다 — `app/llm/parsing.py`의 `render_markdown()`이 파싱된
JSON으로부터 결정론적으로 만들어 낸다. 이렇게 하면 "6개 섹션이 항상 존재"(US-05)를 LLM의
포맷 준수 여부에 기대지 않고 코드로 보장할 수 있다.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.llm.chunking import TimedSegment

_JSON_SCHEMA_DESCRIPTION = """\
반드시 아래 스키마의 순수 JSON 객체 "하나만" 응답하세요. JSON 앞뒤에 설명 문장, 마크다운 코드펜스,
그 어떤 텍스트도 덧붙이지 마세요.

{
  "oneLineSummary": "강의 전체를 한 문장으로 요약한 문자열",
  "keyPoints": [
    { "text": "핵심 주제 설명", "atSeconds": 123.4 }
  ],
  "concepts": [
    { "term": "용어", "description": "설명" }
  ],
  "codeSnippets": [
    { "language": "python", "code": "코드 원문", "description": "이 코드가 무엇인지 설명" }
  ],
  "actionItems": [
    { "text": "과제/공지 내용", "dueDate": "2026-08-27 또는 null" }
  ],
  "keywords": ["복습 키워드1", "복습 키워드2"]
}

규칙:
- 전사 원문은 한 줄에 하나씩 "[MM:SS] 발화 내용" 형식입니다. "MM:SS"는 그 발화가 시작된
  실제 시각입니다.
- "keyPoints"는 3~7개, 강의 전반의 핵심 주제를 다루고 각 항목마다 그 내용이 언급된 줄의
  "[MM:SS]"를 초 단위 숫자로 환산해 "atSeconds"에 반드시 채우세요 (예: "[02:05]" → 125).
  **절대 임의로 추정하지 말고, 반드시 원문에 실제로 적힌 타임코드에서만 가져오세요.**
  여러 줄에 걸친 내용이면 그중 가장 먼저 언급된 줄의 타임코드를 쓰세요.
- "concepts"는 강의에서 설명된 기술/개념 용어를 "용어: 설명" 형태로 정리하세요.
- "codeSnippets"는 강의 중 언급된 코드, CLI 명령어, 문법 예시를 모으세요. 언급이 없으면 빈
  배열 []로 두세요.
- "actionItems"는 과제, 제출 기한, 공지사항만 담으세요. 전사에 과제나 공지가 전혀 없다면
  반드시 빈 배열 []로 응답하세요 (없는 내용을 지어내지 마세요).
- "keywords"는 복습 시 검색할 만한 짧은 키워드 목록입니다.
- 전사에 없는 내용을 지어내지(환각) 마세요. 실제로 언급된 내용만 담으세요.
- 한국어로 응답하되, 영어 기술 용어(라이브러리명, 명령어, 코드 등)는 원문 표기를 그대로 쓰세요.
"""


def format_timecoded_text(segments: Sequence[TimedSegment]) -> str:
    """세그먼트 목록을 "[MM:SS] 텍스트" 형식의 줄 단위 텍스트로 만든다.

    LLM이 `atSeconds`를 추정(환각)하지 않고 실제 타임코드에서 읽어낼 수 있게 하기 위함이다
    (§3.4 "타임스탬프로 원문 대조 가능 → 환각 방어"). 240분(=14,400초) 강의도 분(MM)이
    두 자리를 넘어가면 그대로 자릿수가 늘어날 뿐 잘리지 않는다 (예: "125:07").
    """
    lines = []
    for segment in segments:
        total_seconds = max(int(segment.start_seconds), 0)
        minutes, seconds = divmod(total_seconds, 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {segment.text}")
    return "\n".join(lines)


def build_summary_prompt(
    transcript_text: str,
    *,
    title: str,
    course: str | None = None,
    duration_seconds: float | None = None,
) -> str:
    """전사 텍스트 + 세션 메타데이터로 요약 프롬프트를 만든다 (T-14/T-16 입력 규약)."""
    meta_lines = [f"- 제목: {title}"]
    if course:
        meta_lines.append(f"- 과목: {course}")
    if duration_seconds:
        minutes = duration_seconds / 60
        meta_lines.append(f"- 강의 길이: 약 {minutes:.0f}분")
    meta = "\n".join(meta_lines)

    return (
        "당신은 프로그래밍 수업 조교입니다. 아래는 강의 녹음을 텍스트로 전사한 결과입니다. "
        "이 강의를 복습할 수 있도록 구조화된 요약을 만드세요.\n\n"
        f"[강의 정보]\n{meta}\n\n"
        f"[전사 원문]\n{transcript_text}\n\n"
        f"[출력 형식]\n{_JSON_SCHEMA_DESCRIPTION}"
    )


def build_retry_prompt(original_prompt: str, *, previous_error: str) -> str:
    """형식 위반 시 1회 재요청에 쓸 프롬프트 (§3.4, T-16).

    원본 프롬프트에 "이전 응답이 왜 실패했는지"를 덧붙여, 같은 실수를 반복하지 않도록 유도한다.
    """
    return (
        f"{original_prompt}\n\n"
        "[중요] 이전 응답은 다음 이유로 거부되었습니다: "
        f"{previous_error}\n"
        "다시 응답하세요. 반드시 위에서 지정한 JSON 스키마를 만족하는 순수 JSON 객체 "
        "하나만 출력하세요. 그 외의 텍스트, 설명, 코드펜스는 절대 포함하지 마세요."
    )
