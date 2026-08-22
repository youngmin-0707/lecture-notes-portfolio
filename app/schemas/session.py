"""세션 관련 Pydantic 요청/응답 스키마 (§5.3)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import CamelModel, UtcDateTime


class UpdateSessionRequest(CamelModel):
    """PATCH /api/v1/sessions/{id} 요청 바디 (§5.2 ⑪, P2). 부분 업데이트 — 전부 선택."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    course: str | None = Field(default=None, max_length=100)


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
    """§5.3③ DONE 응답의 `summary` 객체."""

    summary_id: str
    content_markdown: str
    key_points: list[SummaryKeyPointResponse]
    concepts: list[SummaryConceptResponse]
    code_snippets: list[SummaryCodeSnippetResponse]
    action_items: list[SummaryActionItemResponse]
    keywords: list[str]
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
    duration_seconds: float | None
    recorded_at: UtcDateTime
    error_code: str | None = None
    error_message: str | None = None
    progress: ProgressResponse | None = None
    poll_after_seconds: int | None = None
    transcript: TranscriptInfoResponse
    summary: SummaryResponse | None = None


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
