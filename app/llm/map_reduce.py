"""map-reduce 긴 전사 요약 (§3.4, T-21, US-12).

60분 강의 전사는 대략 1.5만~2.5만 토큰이라 통째로 한 번에 넣는 방식은 로컬/무료 티어 컨텍스트
한도를 언젠가 반드시 넘는다. 전사를 오버랩을 둔 청크로 나눠 청크별 부분 요약(map)을 순차
생성한 뒤, 그 부분 요약들을 하나의 입력으로 합쳐 최종 요약(reduce)을 한 번 더 생성한다.

새 프롬프트 템플릿이나 새 파싱 로직을 추가하지 않는다 — map 단계도, reduce 단계도 기존
`build_summary_prompt()` + `generate_structured_summary()`(고정 JSON 스키마 강제 + 형식 위반
1회 재요청)를 그대로 재사용한다. 부분 요약을 다시 합칠 때도 새 포맷을 만들지 않고
`render_markdown()`으로 만든 §3.4 고정 6섹션 마크다운을 그대로 다음 단계의 "전사 원문"
자리에 넣는다 — reduce 단계 입장에서는 "조금 더 압축된 전사"를 요약하는 것과 다르지 않다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence

from app.llm.base import LlmProvider
from app.llm.chunking import TimedSegment, chunk_segments
from app.llm.parsing import render_markdown
from app.llm.prompt import build_summary_prompt, format_timecoded_text
from app.llm.schema import ParsedSummary
from app.llm.summarizer import generate_structured_summary

logger = logging.getLogger("app.llm.map_reduce")


def summarize_transcript(
    provider: LlmProvider,
    segments: Sequence[TimedSegment],
    *,
    title: str,
    course: str | None = None,
    duration_seconds: float | None = None,
    chunk_size_tokens: int,
    overlap_tokens: int,
    call_interval_seconds: float,
    sleep: Callable[[float], None] | None = None,
) -> ParsedSummary:
    """세그먼트 목록으로 구조화 요약을 생성한다. 청크가 1개면 단일 호출, 그 이상이면 map-reduce.

    청크 분할·부분 요약·최종 합성 전체를 "한 번의 시도"로 취급한다 — 호출부
    (`app/pipeline/summarization.py`)의 429/5xx 재시도 루프는 이 함수 전체를 다시 부르는
    것으로 재시도한다(중간 청크부터 재개하지 않는다). map 단계에서 재시도 불가능한 오류가
    나면 그 예외를 그대로 전파해 호출부가 판단하게 한다.
    """
    effective_sleep = sleep if sleep is not None else time.sleep

    chunks = chunk_segments(
        segments, chunk_size_tokens=chunk_size_tokens, overlap_tokens=overlap_tokens
    )
    if len(chunks) <= 1:
        text = format_timecoded_text(chunks[0] if chunks else segments)
        prompt = build_summary_prompt(
            text, title=title, course=course, duration_seconds=duration_seconds
        )
        return generate_structured_summary(provider, prompt)

    logger.info(
        "map-reduce summarization: chunk_count=%d chunk_size_tokens=%d overlap_tokens=%d",
        len(chunks),
        chunk_size_tokens,
        overlap_tokens,
    )

    partial_summaries: list[ParsedSummary] = []
    for index, chunk in enumerate(chunks):
        if index > 0:
            effective_sleep(call_interval_seconds)  # §3.4: 부분 요약은 순차 호출 + 호출 간 간격.
        chunk_prompt = build_summary_prompt(
            format_timecoded_text(chunk),
            title=f"{title} (강의 중 {index + 1}/{len(chunks)}번째 구간)",
            course=course,
        )
        partial_summaries.append(generate_structured_summary(provider, chunk_prompt))

    combined_text = "\n\n".join(
        f"[구간 {index + 1}/{len(partial_summaries)} 요약]\n{render_markdown(partial)}"
        for index, partial in enumerate(partial_summaries)
    )
    final_prompt = build_summary_prompt(
        combined_text, title=title, course=course, duration_seconds=duration_seconds
    )
    return generate_structured_summary(provider, final_prompt)
