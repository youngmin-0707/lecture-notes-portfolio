"""세션 관련 Pydantic 요청/응답 스키마 (§5.3)."""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from app.schemas.common import CamelModel, UtcDateTime


class UpdateSessionRequest(CamelModel):
    """PATCH /api/v1/sessions/{id} 요청 바디 (§5.2 ⑪, P2). 부분 업데이트 — 전부 선택."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    course: str | None = Field(default=None, max_length=100)
    # 2026-10-07: 세션을 다른 일자로 옮긴다(업로드일 ≠ 실제 수업일 바로잡기). 시간대 없는
    # 값은 어느 날짜인지 확정할 수 없어 거부한다 — "몇 일"인지는 사용자의 시간대가 정한다.
    recorded_at: AwareDatetime | None = None


class BulkExportRequest(CamelModel):
    """POST /api/v1/sessions/export 요청 바디 (2026-10-07). 여러 세션 요약을 ZIP으로 받는다."""

    session_ids: list[str] = Field(min_length=1, max_length=200)


class UpdateSummaryRequest(CamelModel):
    """PATCH /api/v1/sessions/{id}/summary 요청 바디 (2026-09-14). 부분 업데이트 — 전부 선택.

    요약 결과가 마음에 들지 않을 때, 재요약(LLM 재호출)을 기다리지 않고 직접 고칠 수 있게
    한다. "핵심 주제"(`keyPoints`, 타임스탬프 포함)는 여기서 건드리지 않는다 — 재생 시각과
    묶여 있는 값이라 텍스트만 따로 고치면 원문과 어긋난다.
    """

    one_line_summary: str | None = Field(default=None, min_length=1, max_length=500)
    detailed_notes_markdown: str | None = Field(default=None, min_length=1, max_length=200_000)


class SessionCreateResponse(CamelModel):
    """POST /api/v1/sessions 응답 (§5.3 ①).

    `autoProcess=true`면 응답 시점 status가 `TRANSCRIBING`, `false`면 `UPLOADED` (T-19).
    """

    session_id: str
    title: str
    course: str | None
    status: str
    source: str
    original_filename: str
    file_size_bytes: int
    duration_seconds: float | None
    recorded_at: UtcDateTime
    created_at: UtcDateTime
    poll_after_seconds: int


class ProcessRequest(CamelModel):
    """POST /api/v1/sessions/{id}/process 요청 바디 (§5.3②). 전부 선택."""

    stt_model: str | None = None
    llm_provider: str | None = None
    skip_summary: bool = False


class ProcessResponse(CamelModel):
    """POST /api/v1/sessions/{id}/process 응답 (§5.3②). 202 Accepted — 즉시 응답."""

    session_id: str
    status: str
    poll_after_seconds: int


class ResummarizeRequest(CamelModel):
    """POST /api/v1/sessions/{id}/summarize 요청 바디 (§5.3⑥). 전부 선택."""

    llm_provider: str | None = None


class SummaryKeyPointResponse(CamelModel):
    """§5.3③ `summary.keyPoints[]` 항목."""

    text: str
    at_seconds: float | None = None


class SummaryConceptResponse(CamelModel):
    """§5.3③ `summary.concepts[]` 항목."""

    term: str
    description: str


class SummaryCodeSnippetResponse(CamelModel):
    """§5.3③ `summary.codeSnippets[]` 항목."""

    language: str
    code: str
    description: str


class SummaryActionItemResponse(CamelModel):
    """§5.3③ `summary.actionItems[]` 항목."""

    text: str
    due_date: str | None = None


class SummaryResponse(CamelModel):
    """§5.3③ DONE 응답의 `summary` 객체.

    `detailed_notes_markdown`이 2026-08-29부터의 주 콘텐츠다(§3.4 개정) — LLM이 강의에
    맞게 자유롭게 구성한 마크다운 본문을 그대로 담는다. `concepts`/`code_snippets`/
    `action_items`는 그 이전 고정 6섹션 방식의 유산으로, 과거 요약과의 호환을 위해 응답에는
    남아 있지만 이후 생성되는 요약에는 항상 빈 배열이다.
    """

    summary_id: str
    content_markdown: str
    key_points: list[SummaryKeyPointResponse]
    concepts: list[SummaryConceptResponse]
    code_snippets: list[SummaryCodeSnippetResponse]
    action_items: list[SummaryActionItemResponse]
    keywords: list[str]
    detailed_notes_markdown: str
    provider: str
    provider_model: str
    created_at: UtcDateTime


class ProgressResponse(CamelModel):
    """§5.3③ "처리 중" 응답의 `progress` 객체."""

    stage: str
    percent: float
    eta_seconds: float | None = None


class TranscriptInfoResponse(CamelModel):
    """§5.3③ 응답에 포함되는 전사 요약 정보 (전문은 ④ 별도 엔드포인트에서 조회)."""

    available: bool
    provider: str | None = None
    provider_model: str | None = None
    character_count: int | None = None
    elapsed_seconds: float | None = None


class SessionDetailResponse(CamelModel):
    """GET /api/v1/sessions/{id} 응답 (§5.3③).

    `summary`는 최신 요약 1건(있다면)을 `SummaryResponse`로 채운다 (T-19, §2.3 "최신 1건이
    기본 표시"). 요약이 아직 없거나(처리 중/미시작) 요약 단계가 실패했다면 `null`이다.
    """

    session_id: str
    title: str
    course: str | None
    status: str
    # 오디오 업로드/녹음/텍스트 파일 업로드를 구분한다 (2026-09-14 `TEXT` 추가). 화면이
    # "오디오가 없다"는 사실을 올바른 이유로 설명하려면 이 값이 필요하다.
    source: str
    duration_seconds: float | None
    recorded_at: UtcDateTime
    error_code: str | None = None
    error_message: str | None = None
    progress: ProgressResponse | None = None
    poll_after_seconds: int | None = None
    transcript: TranscriptInfoResponse
    summary: SummaryResponse | None = None
    audio_available: bool


class TranscriptSegmentResponse(CamelModel):
    """§5.3④ `segments[]` 항목."""

    seq: int
    start_seconds: float
    end_seconds: float
    text: str


class TranscriptDetailResponse(CamelModel):
    """GET /api/v1/sessions/{id}/transcript 응답 (§5.3④)."""

    session_id: str
    language: str
    corrected: bool
    text: str
    segments: list[TranscriptSegmentResponse]


class SessionListItemResponse(CamelModel):
    """GET /api/v1/sessions 응답의 `items[]` 항목 (§5.3⑤, US-14).

    전체 전사/요약 본문은 절대 포함하지 않는다 — 목록 응답이 수 MB가 되는 것을 막기 위함.
    """

    session_id: str
    title: str
    course: str | None
    status: str
    duration_seconds: float | None
    recorded_at: UtcDateTime
    summary_preview: str | None = None


class SessionListResponse(CamelModel):
    """GET /api/v1/sessions 응답 (§5.3⑤)."""

    items: list[SessionListItemResponse]
    page: int
    size: int
    total_count: int
    total_pages: int
