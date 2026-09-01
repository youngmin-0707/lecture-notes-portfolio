"""복습 문제 생성 프롬프트 구성 (2026-09-01 신규, 복습 문제 자동 생성 기능).

요약(`app/llm/prompt.py`)이 만든 자유형식 본문(`detailed_notes_markdown`)을 근거 자료로
써서 복습 문제를 만든다 — 원본 전사를 다시 통째로 넘기지 않는다. `detailedNotes`는 이미
강의 전체를 빠짐없이 다루도록 검증된 자료라(§3.4), 여기서 다시 map-reduce로 청크를 나눌
필요가 없고(한 번의 호출로 충분), 질문의 정답 근거도 이 텍스트 안에서 바로 찾을 수 있어야
한다는 제약을 프롬프트에 명시한다(환각 방지).

`app/llm/prompt.py`의 `build_retry_prompt()`를 형식위반 재요청에 그대로 재사용한다 — 그
함수는 요약 전용 내용이 없는 범용 함수다.
"""

from __future__ import annotations

_QUESTION_COUNT = 5

QUIZ_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["question", "answer"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

_JSON_SCHEMA_DESCRIPTION = f"""\
반드시 아래 스키마의 순수 JSON 객체 "하나만" 응답하세요. JSON 앞뒤에 설명 문장, 마크다운 코드펜스,
그 어떤 텍스트도 덧붙이지 마세요.

{{
  "questions": [
    {{ "question": "복습용 질문 (한 문장)", "answer": "강의 내용에 근거한 정답 설명 (2~4문장)" }}
  ]
}}

당신은 이 강의를 들은 학생이 스스로 복습할 수 있도록 문제를 내는 조교입니다. 아래 [강의 노트]를
유일한 근거 자료로 삼아 문제 {_QUESTION_COUNT}개를 만드세요.

규칙:
- 단순 사실 암기("OOO의 정의는?")보다, "왜 이렇게 하나요?", "OOO 대신 XXX를 쓰면 어떻게 되나요?",
  "A와 B를 분리하는 이유는 무엇인가요?"처럼 **이해도를 확인하는 질문**을 우선하세요. 강의에서
  실제로 설명한 이유·비교·트레이드오프가 있다면 그것을 묻는 질문을 만드세요.
- 질문끼리 서로 다른 주제/섹션을 다루도록 고르게 분산하세요. 같은 개념을 여러 각도로 반복해서
  묻지 마세요.
- "answer"는 [강의 노트]에 실제로 쓰인 내용만 근거로 삼아 설명하세요. 강의에 없는 사실을
  지어내지(환각) 마세요 — [강의 노트]로 답할 수 없는 질문은 애초에 만들지 마세요.
- "answer"는 "정답: OOO"처럼 단답으로 끝내지 말고, 왜 그런지까지 2~4문장으로 설명하세요.
- 한국어로 응답하되, 영어 기술 용어(라이브러리명, 명령어, 코드 등)는 원문 표기를 그대로 쓰세요.
"""


def build_quiz_prompt(
    detailed_notes_markdown: str,
    *,
    title: str,
    course: str | None = None,
) -> str:
    """강의 노트(요약의 자유형식 본문)로 복습 문제 생성 프롬프트를 만든다."""
    meta_lines = [f"- 제목: {title}"]
    if course:
        meta_lines.append(f"- 과목: {course}")
    meta = "\n".join(meta_lines)

    return (
        "당신은 프로그래밍 수업 조교입니다. 아래는 이미 정리된 강의 노트입니다. "
        "이 강의를 복습할 수 있도록 문제를 만드세요.\n\n"
        f"[강의 정보]\n{meta}\n\n"
        f"[강의 노트]\n{detailed_notes_markdown}\n\n"
        f"[출력 형식]\n{_JSON_SCHEMA_DESCRIPTION}"
    )
