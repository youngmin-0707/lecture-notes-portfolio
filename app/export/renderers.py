"""내보내기 본문 렌더러 — markdown / txt / srt (§5.3⑦, T-27).

`app/llm/parsing.py`의 `render_markdown()`(§3.4 고정 6섹션)을 그대로 재사용한다 — 요약
섹션 포맷을 여기서 새로 만들지 않는다.
"""

from __future__ import annotations

from datetime import datetime

from app.models.summary import Summary
from app.models.transcript import Transcript


def _transcript_text(transcript: Transcript) -> str:
    """보정본이 있으면 보정본, 없으면 원본을 쓴다 (T-13 `GET .../transcript` 기본값과 동일 관례)."""
    return transcript.text_corrected or transcript.text_raw


def render_txt_export(transcript: Transcript) -> str:
    """`txt` 포맷: 전사 전문만 (§5.3⑦)."""
    return _transcript_text(transcript)


def render_markdown_export(
    *,
    title: str,
    course: str | None,
    recorded_at: datetime,
    transcript: Transcript | None,
    summary: Summary | None,
) -> str:
    """`md` 포맷: 메타데이터 + 요약 + 전사 전문 (§5.3⑦, US-16).

    `transcript`가 `None`이면 전사 전문 섹션을 빼고 요약만 담는다 (여러 세션 ZIP 내보내기).
    """
    lines = [f"# {title}", ""]
    lines.append(f"- 과목: {course}" if course else "- 과목: (미지정)")
    lines.append(f"- 녹음일: {recorded_at:%Y-%m-%d}")
    lines.append("")
    lines.append(summary.content_markdown if summary is not None else "*요약이 아직 없습니다.*")
    if transcript is not None:
        lines += ["", "## 전사 전문", "", _transcript_text(transcript)]
    return "\n".join(lines)


def _format_srt_timestamp(seconds: float) -> str:
    """ "HH:MM:SS,mmm" 형식으로 변환한다 (§5.3⑦, US-16 SRT 타임코드 규격)."""
    total_ms = max(round(seconds * 1000), 0)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def render_srt_export(transcript: Transcript) -> str:
    """`srt` 포맷: 세그먼트 자막 (§5.3⑦)."""
    blocks = []
    for index, segment in enumerate(sorted(transcript.segments, key=lambda s: s.seq), start=1):
        start = _format_srt_timestamp(segment.start_seconds)
        end = _format_srt_timestamp(segment.end_seconds)
        blocks.append(f"{index}\n{start} --> {end}\n{segment.text}\n")
    return "\n".join(blocks)
