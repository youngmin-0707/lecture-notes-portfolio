"""전사 청크 분할 (§3.4 map-reduce, T-21).

`transcript_segments`(세그먼트 단위, 타임스탬프 보유)를 최소 단위로 다뤄 문장/세그먼트를
중간에 자르지 않는다. 청크 크기·오버랩은 "토큰"으로 지정되지만, 실제 판단은 문자 수 근사치로
한다 — qwen3 등 로컬 모델 전용 토크나이저를 별도로 붙이지 않고도 "약 N토큰" 수준의 근사를
충분히 얻을 수 있다(§3.4가 요구하는 정밀도도 "약"이다).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# 한국어(한글 음절) 위주 전사 텍스트에 대한 대략적인 문자당 토큰 근사치. 정밀한 토크나이저
# 실측값이 아니라 "청크가 대략 목표 토큰 수 근방이 되게 하는" 근사 상수다.
CHARS_PER_TOKEN_ESTIMATE = 2.2


@dataclass(frozen=True)
class TimedSegment:
    """청크 분할·타임코드 표기에 필요한 최소 정보만 담은 세그먼트 (ORM과 분리)."""

    start_seconds: float
    text: str


def estimate_tokens(text: str) -> int:
    """문자 수 기반 토큰 근사치. 빈 문자열이 아니면 최소 1을 반환한다."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def _take_overlap_tail(chunk: list[TimedSegment], overlap_chars: float) -> list[TimedSegment]:
    """청크 끝에서부터 `overlap_chars` 예산 안에 드는 만큼 세그먼트를 되감아 반환한다.

    최소 1개는 항상 포함한다(청크가 비어있지 않은 한) — 그래야 다음 청크가 완전히 새
    시작점에서 출발하지 않고 실제로 이전 청크와 겹치는 문맥을 갖는다.
    """
    tail: list[TimedSegment] = []
    total_chars = 0
    for segment in reversed(chunk):
        segment_chars = len(segment.text)
        if tail and total_chars + segment_chars > overlap_chars:
            break
        tail.append(segment)
        total_chars += segment_chars
    tail.reverse()
    return tail


def chunk_segments(
    segments: Sequence[TimedSegment],
    *,
    chunk_size_tokens: int,
    overlap_tokens: int,
) -> list[list[TimedSegment]]:
    """세그먼트 목록을 오버랩을 둔 청크로 분할한다 (§3.4).

    세그먼트 하나가 `chunk_size_tokens`보다 커도 쪼개지 않는다 — 그 세그먼트만으로 이뤄진
    청크가 된다 (드문 경우지만 무한루프/데이터 손실을 막기 위한 방어).

    Returns:
        청크 목록. 세그먼트가 비어 있으면 빈 리스트. 전체가 한 청크에 들어가면 길이 1인
        리스트(청크 1개, 오버랩 없음)를 반환한다.
    """
    if not segments:
        return []

    chunk_size_chars = chunk_size_tokens * CHARS_PER_TOKEN_ESTIMATE
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN_ESTIMATE

    chunks: list[list[TimedSegment]] = []
    current: list[TimedSegment] = []
    current_chars = 0

    for segment in segments:
        segment_chars = len(segment.text)
        if current and current_chars + segment_chars > chunk_size_chars:
            chunks.append(current)
            current = _take_overlap_tail(current, overlap_chars)
            current_chars = sum(len(s.text) for s in current)
        current.append(segment)
        current_chars += segment_chars

    if current:
        chunks.append(current)

    return chunks
