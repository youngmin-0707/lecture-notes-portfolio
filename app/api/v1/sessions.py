"""세션 API (§5.3).

`db` 의존성은 전부 `Depends(get_db, scope="function")`로 선언한다 — FastAPI 0.118+ 기본값인
`scope="request"`는 의존성 종료 코드(`get_db`의 `db.commit()`)를 응답 전송 "이후"(=
`BackgroundTasks` 실행과 같은 시점 또는 그 이후)로 미루는데, 이 라우터의 `create_session`/
`process_session`은 커밋 직후 같은 세션 행을 만지는 `BackgroundTasks`를 예약한다.
`scope="function"`이 아니면 요청 트랜잭션의 커밋이 아직 끝나지 않은 상태에서 백그라운드
작업이 같은 행에 UPDATE를 시도해 실제로 Postgres 행 잠금 경합(데드락처럼 보이는 무한 대기)이
발생함을 실측으로 확인했다 (T-19). 참고: https://fastapi.tiangolo.com/advanced/advanced-dependencies/
"""

from __future__ import annotations

import io
import math
import zipfile
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DBSession

from app.audio.storage import SavedUpload, delete_stored_file, save_upload_stream
from app.audio.validation import detect_audio_format, probe_audio, validate_duration_seconds
from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.export import (
    build_content_disposition,
    build_export_filename,
    render_markdown_export,
    render_srt_export,
    render_txt_export,
)
from app.glossary.correction import correct_transcript_text, fetch_applicable_terms
from app.llm.parsing import extract_one_line_summary, render_markdown
from app.llm.schema import ParsedSummary, SummaryKeyPoint
from app.models.enums import QuizStatus, SessionSource, SessionStatus
from app.models.quiz import Quiz
from app.models.session import Session as SessionModel
from app.models.summary import Summary
from app.models.transcript import Transcript
from app.pipeline.orchestration import (
    generate_quiz_in_background,
    resummarize_session_in_background,
    run_pipeline_in_background,
)
from app.pipeline.progress import ProgressInfo, get_progress
from app.schemas.quiz import (
    CreateQuizRequest,
    QuizQuestionResponse,
    QuizResponse,
    QuizTriggerResponse,
)
from app.schemas.session import (
    BulkExportRequest,
    ProcessRequest,
    ProcessResponse,
    ProgressResponse,
    ResummarizeRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionListItemResponse,
    SessionListResponse,
    SummaryActionItemResponse,
    SummaryCodeSnippetResponse,
    SummaryConceptResponse,
    SummaryKeyPointResponse,
    SummaryResponse,
    TranscriptDetailResponse,
    TranscriptInfoResponse,
    TranscriptSegmentResponse,
    UpdateSessionRequest,
    UpdateSummaryRequest,
)
from app.text.validation import (
    is_text_upload,
    load_text_upload,
    text_mime_type,
    text_upload_extension,
)

# §5.3⑤ summaryPreview: 목록에 본문을 싣지 않으려고 짧게 자른다.
SUMMARY_PREVIEW_MAX_LENGTH = 200

router = APIRouter(tags=["sessions"])

# 처리 중(TRANSCRIBING/SUMMARIZING) 상태에서 진행률 스토어에 값이 없을 때 쓰는 기본값.
_PROCESSING_STATUSES = {SessionStatus.TRANSCRIBING.value, SessionStatus.SUMMARIZING.value}

# ③ GET /sessions/{id} 폴링 안내용 기본 간격 (§5.3 ①③).
DEFAULT_POLL_AFTER_SECONDS = 10


def _default_title(now: datetime) -> str:
    return f"{now:%Y-%m-%d} 수업"


# 텍스트 업로드로 만들어진 `transcripts` 행의 provider 값 (2026-09-14). STT provider 이름
# 자리에 "전사한 것이 아니라 사용자가 올린 텍스트"임을 남겨, 나중에 전사 출처를 구분할 수 있게 한다.
TEXT_UPLOAD_TRANSCRIPT_PROVIDER = "text_upload"


async def _save_upload_for_create(file: UploadFile, *, is_text: bool) -> SavedUpload:
    """업로드를 디스크에 저장한다. 텍스트 업로드는 용량 한도·에러 문구가 오디오와 다르다."""
    if not is_text:
        return await save_upload_stream(file)

    try:
        return await save_upload_stream(file, max_bytes=settings.MAX_TEXT_UPLOAD_SIZE_BYTES)
    except AppError as exc:
        if exc.code == "FILE_TOO_LARGE":
            limit_mb = settings.MAX_TEXT_UPLOAD_SIZE_BYTES // (1024 * 1024)
            raise AppError(
                "FILE_TOO_LARGE", message=f"텍스트 파일 크기가 최대 {limit_mb}MB를 초과합니다."
            ) from exc
        if exc.code == "INVALID_AUDIO_FILE":  # 빈 파일 — 텍스트 경로에서는 "내용 없음"이다.
            raise AppError("TEXT_TOO_SHORT") from exc
        raise


def _persist_uploaded_text_as_transcript(db: DBSession, session: SessionModel, text: str) -> None:
    """업로드된 텍스트를 그대로 전사 1건으로 저장한다 (2026-09-14).

    세그먼트(시간 구간)는 만들지 않는다 — 타임스탬프가 없는 자료이기 때문이다. 요약
    파이프라인은 세그먼트가 없으면 본문 전체를 0초 시점 세그먼트 하나로 취급하므로
    (`app/pipeline/summarization.py::_build_timed_segments`) 별도 분기 없이 그대로 요약된다.
    용어집 보정(§3.3)은 전사 경로와 똑같이 적용한다.
    """
    glossary_terms = fetch_applicable_terms(db, session.course)
    db.add(
        Transcript(
            session_id=session.id,
            text_raw=text,
            text_corrected=correct_transcript_text(text, glossary_terms),
            language=settings.STT_LANGUAGE,
            provider=TEXT_UPLOAD_TRANSCRIPT_PROVIDER,
            provider_model=text_upload_extension(session.original_filename) or "txt",
            elapsed_seconds=None,
        )
    )
    db.flush()


@router.post("/sessions", status_code=201, response_model=SessionCreateResponse)
async def create_session(
    file: Annotated[UploadFile, File()],
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    background_tasks: BackgroundTasks,
    title: Annotated[str | None, Form(max_length=200)] = None,
    course: Annotated[str | None, Form(max_length=100)] = None,
    autoProcess: Annotated[bool, Form()] = True,  # noqa: N803 (§5.1 camelCase 요청 필드)
) -> SessionCreateResponse:
    """오디오 또는 텍스트 파일 업로드로 세션을 만든다 (§5.3①, 2026-09-14 텍스트 지원 추가).

    텍스트 파일(.txt/.md)은 전사할 것이 없으므로 업로드 본문이 곧바로 `transcripts`가 되고,
    `autoProcess=true`면 전사 단계를 건너뛴 채 요약(`SUMMARIZING`)부터 시작한다.
    """
    is_text = is_text_upload(file.filename)
    saved = await _save_upload_for_create(file, is_text=is_text)

    try:
        if is_text:
            text = load_text_upload(saved.path)
            mime_type = text_mime_type(file.filename)
            source = SessionSource.TEXT.value
            audio_path = None
            duration_seconds = None
        else:
            detected = detect_audio_format(saved.header)
            if detected is None:
                raise AppError("UNSUPPORTED_AUDIO_FORMAT")
            _format_key, mime_type = detected

            probe = probe_audio(saved.path)
            validate_duration_seconds(probe.duration_seconds)
            source = SessionSource.UPLOAD.value
            audio_path = str(saved.path)
            duration_seconds = probe.duration_seconds

        now = datetime.now(UTC)
        explicit_title = (title or "").strip()
        session = SessionModel(
            title=explicit_title or _default_title(now),
            # 업로드 시 제목을 직접 입력했다면 요약 완료 후 자동 제목으로 덮어쓰지 않는다.
            title_customized=bool(explicit_title),
            course=course,
            status=SessionStatus.UPLOADED.value,
            source=source,
            audio_path=audio_path,
            original_filename=file.filename or ("lecture.txt" if is_text else "audio"),
            mime_type=mime_type,
            file_size_bytes=saved.total_bytes,
            duration_seconds=duration_seconds,
            recorded_at=now,
        )
        db.add(session)
        db.flush()
        if is_text:
            _persist_uploaded_text_as_transcript(db, session, text)
            # 전사에 해당하는 내용이 이미 확보됐으므로 UPLOADED가 아니라 TRANSCRIBED에서 출발한다.
            session.status = SessionStatus.TRANSCRIBED.value
            db.flush()
        db.refresh(session)
    except Exception:
        # §5.3 ①: 검증 실패 시 파일 미저장, 저장(DB) 실패 시 레코드·파일 모두 롤백.
        delete_stored_file(saved.path)
        raise

    if is_text:
        # 본문이 이미 DB(transcripts)에 들어갔으니 업로드 원본 파일은 남길 이유가 없다
        # (오디오도 요약이 끝나면 지우는 §2026-08-29 정책과 같은 취지).
        delete_stored_file(saved.path)

    # US-02, T-19: autoProcess=true면 응답 시점 status가 TRANSCRIBING이고, 전사→요약이
    # 백그라운드로 자동 시작된다 (§5.3①). 텍스트 업로드는 전사가 이미 있으므로
    # `run_pipeline()`이 STT를 건너뛰고 요약만 하며, 응답 status도 SUMMARIZING이다.
    if autoProcess:
        session.status = (
            SessionStatus.SUMMARIZING.value if is_text else SessionStatus.TRANSCRIBING.value
        )
        db.flush()
        background_tasks.add_task(run_pipeline_in_background, session.id)

    return SessionCreateResponse(
        session_id=session.id,
        title=session.title,
        course=session.course,
        status=session.status,
        source=session.source,
        original_filename=session.original_filename,
        file_size_bytes=session.file_size_bytes,
        duration_seconds=session.duration_seconds,
        recorded_at=session.recorded_at,
        created_at=session.created_at,
        poll_after_seconds=DEFAULT_POLL_AFTER_SECONDS,
    )


def _extract_summary_preview(
    content_markdown: str, *, max_length: int = SUMMARY_PREVIEW_MAX_LENGTH
) -> str:
    """`content_markdown`의 "## 한 줄 요약" 섹션만 뽑아 미리보기로 자른다 (§5.3⑤).

    새 스키마·필드를 추가하지 않고, 항상 존재가 보장되는 6섹션 마크다운(US-05)의 첫 섹션에서
    결정론적으로 추출한다. 추출 자체는 `extract_one_line_summary()`(2026-09-14, 요약 수정
    라우트와 공유)에 위임하고 여기서는 미리보기 길이로 자르기만 한다.
    """
    return extract_one_line_summary(content_markdown)[:max_length]


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    course: str | None = None,
    status: SessionStatus | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SessionListResponse:
    """세션 목록 조회 (§5.3⑤, US-14). 최근 녹음순, 과목·상태·제목/내용 검색·날짜 범위 필터 +
    페이징 (2026-08-30: `q`/`date_from`/`date_to` 추가 — 홈 화면 세션 목록에서 바로 좁혀
    보기 위함. 전문 검색+스니펫이 필요하면 `GET /search`를 쓴다; 이건 그보다 가벼운 목록
    필터다).
    """
    filters = []
    if course is not None:
        filters.append(SessionModel.course == course)
    if status is not None:
        filters.append(SessionModel.status == status.value)
    if date_from is not None:
        filters.append(SessionModel.recorded_at >= datetime.combine(date_from, time.min, UTC))
    if date_to is not None:
        filters.append(SessionModel.recorded_at <= datetime.combine(date_to, time.max, UTC))
    if q is not None:
        like_pattern = f"%{q.strip().lower()}%"
        # "제목 또는 (최신 요약) 내용"에 매칭되는 세션 id만 추린다. 세션당 최신 요약 1건만
        # 봐야 하므로(§2.3) row_number()로 세션별 최신 행을 뽑는 서브쿼리를 쓴다 — 목록
        # 페이지네이션(count/limit) 쿼리 구조를 안 건드리고 필터 하나로 얹을 수 있다.
        ranked_summaries = (
            select(
                Summary.session_id,
                Summary.content_markdown,
                func.row_number()
                .over(partition_by=Summary.session_id, order_by=Summary.created_at.desc())
                .label("rn"),
            )
        ).subquery()
        latest_summary = (
            select(ranked_summaries.c.session_id, ranked_summaries.c.content_markdown).where(
                ranked_summaries.c.rn == 1
            )
        ).subquery()
        matching_ids = (
            select(SessionModel.id)
            .outerjoin(latest_summary, latest_summary.c.session_id == SessionModel.id)
            .where(
                or_(
                    func.lower(SessionModel.title).like(like_pattern),
                    func.lower(latest_summary.c.content_markdown).like(like_pattern),
                )
            )
        )
        filters.append(SessionModel.id.in_(matching_ids))

    total_count = db.execute(
        select(func.count()).select_from(SessionModel).where(*filters)
    ).scalar_one()

    page_sessions = (
        db.execute(
            select(SessionModel)
            .where(*filters)
            .order_by(SessionModel.recorded_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        .scalars()
        .all()
    )

    session_ids = [s.id for s in page_sessions]
    latest_summary_by_session: dict[str, Summary] = {}
    if session_ids:
        # session_id, created_at DESC로 정렬하면 각 session_id 그룹의 첫 행이 최신 요약이다
        # — 세션마다 별도 쿼리(N+1)를 날리지 않고 한 번에 가져온다.
        for summary in (
            db.execute(
                select(Summary)
                .where(Summary.session_id.in_(session_ids))
                .order_by(Summary.session_id, Summary.created_at.desc())
            )
            .scalars()
            .all()
        ):
            latest_summary_by_session.setdefault(summary.session_id, summary)

    items = [
        SessionListItemResponse(
            session_id=s.id,
            title=s.title,
            course=s.course,
            status=s.status,
            duration_seconds=s.duration_seconds,
            recorded_at=s.recorded_at,
            summary_preview=(
                _extract_summary_preview(latest_summary_by_session[s.id].content_markdown)
                if s.id in latest_summary_by_session
                else None
            ),
        )
        for s in page_sessions
    ]

    return SessionListResponse(
        items=items,
        page=page,
        size=size,
        total_count=total_count,
        total_pages=math.ceil(total_count / size) if total_count else 0,
    )


@router.post("/sessions/{session_id}/process", status_code=202, response_model=ProcessResponse)
def process_session(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    background_tasks: BackgroundTasks,
    body: Annotated[ProcessRequest | None, Body()] = None,
) -> ProcessResponse:
    """전사 + 요약 실행 (§5.3②, US-02).

    202 Accepted로 즉시 응답하고, 실제 처리는 `BackgroundTasks`로 예약한다 — 전사는 수 분이
    걸리므로 동기 응답으로 만들면 타임아웃이 나고 UI가 멈춘다.
    """
    session = _get_session_or_404(db, session_id)
    if session.status in _PROCESSING_STATUSES:
        raise AppError("INVALID_SESSION_STATE")

    request = body or ProcessRequest()

    # 전사가 이미 있으면 `run_pipeline()`이 STT를 건너뛰고 요약만 한다(§2.4) — 텍스트 업로드
    # 세션의 재시도가 대표적이다. 그 경우 응답 status도 실제로 하게 될 일(SUMMARIZING)로
    # 알려준다. "전사 중"이라고 표시해두면 화면에 잘못된 단계가 보인다 (2026-09-14).
    has_transcript = (
        db.execute(select(Transcript.id).where(Transcript.session_id == session.id)).first()
        is not None
    )
    session.status = (
        SessionStatus.SUMMARIZING.value
        if has_transcript and not request.skip_summary
        else SessionStatus.TRANSCRIBING.value
    )
    session.error_code = None
    session.error_message = None
    db.flush()

    background_tasks.add_task(
        run_pipeline_in_background,
        session.id,
        stt_model=request.stt_model,
        llm_provider_name=request.llm_provider,
        skip_summary=request.skip_summary,
    )

    return ProcessResponse(
        session_id=session.id,
        status=session.status,
        poll_after_seconds=DEFAULT_POLL_AFTER_SECONDS,
    )


# ⑥ POST /sessions/{id}/summarize 폴링 안내용 간격 — 재요약은 전사 없이 요약만 하므로
# 전체 파이프라인(process)보다 짧게 안내한다 (§5.3⑥ 예시값).
RESUMMARIZE_POLL_AFTER_SECONDS = 5


@router.post("/sessions/{session_id}/summarize", status_code=202, response_model=ProcessResponse)
def resummarize_session(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    background_tasks: BackgroundTasks,
    body: Annotated[ResummarizeRequest | None, Body()] = None,
) -> ProcessResponse:
    """요약만 재실행한다 (§5.3⑥, US-17). 기존 전사를 그대로 쓰고 다시 전사하지 않는다.

    `DONE`이든 요약 단계 `FAILED`든 재요청할 수 있다. 새 `summaries` 레코드가 추가되고
    기존 요약은 그대로 남는다(§2.3 "세션당 여러 건을 허용" — 다른 모델로 재요약해 비교
    가능).
    """
    session = _get_session_or_404(db, session_id)

    has_transcript = (
        db.execute(select(Transcript.id).where(Transcript.session_id == session.id)).first()
        is not None
    )
    if not has_transcript:
        raise AppError("TRANSCRIPT_NOT_READY")

    if session.status in _PROCESSING_STATUSES:
        raise AppError("INVALID_SESSION_STATE")

    request = body or ResummarizeRequest()

    session.status = SessionStatus.SUMMARIZING.value
    session.error_code = None
    session.error_message = None
    db.flush()

    background_tasks.add_task(
        resummarize_session_in_background,
        session.id,
        llm_provider_name=request.llm_provider,
    )

    return ProcessResponse(
        session_id=session.id,
        status=session.status,
        poll_after_seconds=RESUMMARIZE_POLL_AFTER_SECONDS,
    )


def _get_session_or_404(db: DBSession, session_id: str) -> SessionModel:
    session = db.get(SessionModel, session_id)
    if session is None:
        raise AppError("SESSION_NOT_FOUND")
    return session


def _resolve_progress(session: SessionModel) -> ProgressInfo | None:
    if session.status not in _PROCESSING_STATUSES:
        return None
    stored = get_progress(session.id)
    if stored is not None:
        return stored
    # 스토어에 값이 없을 수 있다 (예: 서버 재시작 직후, 또는 상태만 수동으로 맞춘 테스트).
    return ProgressInfo(stage=session.status, percent=0.0, eta_seconds=None)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session_detail(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> SessionDetailResponse:
    """세션 상세 조회 (§5.3③). 처리 실패(FAILED)여도 HTTP 200을 반환한다."""
    session = _get_session_or_404(db, session_id)
    return _build_session_detail_response(db, session)


@router.patch("/sessions/{session_id}", response_model=SessionDetailResponse)
def update_session_metadata(
    session_id: str,
    body: UpdateSessionRequest,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> SessionDetailResponse:
    """제목/과목 수정 (§5.2 ⑪, P2). §5.3에 상세 스펙이 없어 기존 관례를 그대로 따른다:

    부분 업데이트(요청에 포함된 필드만 갱신), 처리 중 상태와 무관하게 언제나 허용(메타데이터
    수정은 파이프라인에 영향을 주지 않는다), 응답은 `GET /sessions/{id}`와 동일한 상세
    구조(즉시 반영된 값을 화면에서 바로 확인할 수 있게).
    """
    session = _get_session_or_404(db, session_id)
    if body.title is not None:
        session.title = body.title
        # 사용자가 직접 제목을 정했다는 뜻이므로, 이후 재요약해도 자동 제목이 덮어쓰지 않는다.
        session.title_customized = True
    if body.course is not None:
        session.course = body.course
    if body.recorded_at is not None:
        session.recorded_at = body.recorded_at.astimezone(UTC)
    db.flush()
    return _build_session_detail_response(db, session)


@router.patch("/sessions/{session_id}/summary", response_model=SessionDetailResponse)
def update_summary(
    session_id: str,
    body: UpdateSummaryRequest,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> SessionDetailResponse:
    """요약 내용을 사용자가 직접 고친다 (2026-09-14, "요약이 마음에 안 들 때" 대응).

    LLM을 다시 호출하는 재요약(`POST .../summarize`, §5.3⑥)과 달리 비용·시간 없이 즉시
    반영된다. `content_markdown`은 항상 `render_markdown()`으로 다시 조립해 최신 상태로
    맞춘다 — MD 내보내기(§5.3⑦)와 목록 미리보기(§5.3⑤)가 이 필드를 그대로 쓰기 때문이다.
    두 필드 중 하나만 보내면 나머지는 현재 값을 그대로 유지한 채 재조립한다.
    """
    session = _get_session_or_404(db, session_id)
    if session.status in _PROCESSING_STATUSES:
        # 백그라운드 파이프라인이 같은 summaries 행을 새로 쓰는 중일 수 있다 — 경합 방지.
        raise AppError("INVALID_SESSION_STATE")

    summary = db.execute(
        select(Summary)
        .where(Summary.session_id == session.id)
        .order_by(Summary.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if summary is None:
        raise AppError("SUMMARY_NOT_READY")

    one_line_summary = (
        body.one_line_summary.strip()
        if body.one_line_summary is not None
        else extract_one_line_summary(summary.content_markdown)
    )
    detailed_notes_markdown = (
        body.detailed_notes_markdown.strip()
        if body.detailed_notes_markdown is not None
        else summary.detailed_notes_markdown
    )

    parsed = ParsedSummary(
        one_line_summary=one_line_summary,
        key_points=[
            SummaryKeyPoint(text=p["text"], at_seconds=p.get("atSeconds"))
            for p in summary.key_points
        ],
        keywords=list(summary.keywords),
        detailed_notes=detailed_notes_markdown,
    )
    summary.content_markdown = render_markdown(parsed)
    summary.detailed_notes_markdown = detailed_notes_markdown
    db.flush()

    return _build_session_detail_response(db, session)


def _build_session_detail_response(db: DBSession, session: SessionModel) -> SessionDetailResponse:
    transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()

    if transcript is not None:
        text = transcript.text_corrected or transcript.text_raw
        transcript_info = TranscriptInfoResponse(
            available=True,
            provider=transcript.provider,
            provider_model=transcript.provider_model,
            character_count=len(text),
            elapsed_seconds=transcript.elapsed_seconds,
        )
    else:
        transcript_info = TranscriptInfoResponse(available=False)

    latest_summary = db.execute(
        select(Summary)
        .where(Summary.session_id == session.id)
        .order_by(Summary.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    summary_response = (
        SummaryResponse(
            summary_id=latest_summary.id,
            content_markdown=latest_summary.content_markdown,
            key_points=[
                SummaryKeyPointResponse(text=p["text"], at_seconds=p.get("atSeconds"))
                for p in latest_summary.key_points
            ],
            concepts=[
                SummaryConceptResponse(term=c["term"], description=c["description"])
                for c in latest_summary.concepts
            ],
            code_snippets=[
                SummaryCodeSnippetResponse(
                    language=s["language"], code=s["code"], description=s.get("description", "")
                )
                for s in latest_summary.code_snippets
            ],
            action_items=[
                SummaryActionItemResponse(text=a["text"], due_date=a.get("dueDate"))
                for a in latest_summary.action_items
            ],
            keywords=list(latest_summary.keywords),
            detailed_notes_markdown=latest_summary.detailed_notes_markdown,
            provider=latest_summary.provider,
            provider_model=latest_summary.provider_model,
            created_at=latest_summary.created_at,
        )
        if latest_summary is not None
        else None
    )

    progress = _resolve_progress(session)
    progress_response = (
        ProgressResponse(
            stage=progress.stage, percent=progress.percent, eta_seconds=progress.eta_seconds
        )
        if progress is not None
        else None
    )

    return SessionDetailResponse(
        session_id=session.id,
        title=session.title,
        course=session.course,
        status=session.status,
        source=session.source,
        duration_seconds=session.duration_seconds,
        recorded_at=session.recorded_at,
        error_code=session.error_code,
        error_message=session.error_message,
        progress=progress_response,
        poll_after_seconds=DEFAULT_POLL_AFTER_SECONDS if progress is not None else None,
        transcript=transcript_info,
        summary=summary_response,
        audio_available=bool(session.audio_path and Path(session.audio_path).is_file()),
    )


@router.get("/sessions/{session_id}/transcript", response_model=TranscriptDetailResponse)
def get_session_transcript(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    corrected: bool = True,
) -> TranscriptDetailResponse:
    """전사 전문 + 세그먼트 조회 (§5.3④, US-04).

    `corrected=true`(기본)를 요청해도 아직 `text_corrected`가 채워지지 않았다면
    (용어집 보정은 그룹 E/T-23) `text_raw`로 폴백한다.
    """
    session = _get_session_or_404(db, session_id)

    transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()
    if transcript is None:
        raise AppError("TRANSCRIPT_NOT_READY")

    used_corrected = corrected and transcript.text_corrected is not None
    text = transcript.text_corrected if used_corrected else transcript.text_raw

    segments = [
        TranscriptSegmentResponse(
            seq=segment.seq,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            text=segment.text,
        )
        for segment in sorted(transcript.segments, key=lambda s: s.seq)
    ]

    return TranscriptDetailResponse(
        session_id=session.id,
        language=transcript.language,
        corrected=used_corrected,
        text=text,
        segments=segments,
    )


# 복습 탭 폴링 안내용 간격 (2026-09-01) — 단일 LLM 호출이라 요약보다 짧게 잡는다.
QUIZ_POLL_AFTER_SECONDS = 3

_QUIZ_ACTIVE_STATUSES = {QuizStatus.GENERATING.value}


def _latest_quiz(db: DBSession, session_id: str) -> Quiz | None:
    return db.execute(
        select(Quiz).where(Quiz.session_id == session_id).order_by(Quiz.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def _quiz_to_response(quiz: Quiz) -> QuizResponse:
    return QuizResponse(
        quiz_id=quiz.id,
        session_id=quiz.session_id,
        status=quiz.status,
        questions=[
            QuizQuestionResponse(question=q["question"], answer=q["answer"]) for q in quiz.questions
        ],
        error_code=quiz.error_code,
        error_message=quiz.error_message,
        poll_after_seconds=(
            QUIZ_POLL_AFTER_SECONDS if quiz.status in _QUIZ_ACTIVE_STATUSES else None
        ),
        created_at=quiz.created_at,
    )


@router.post("/sessions/{session_id}/quiz", status_code=202, response_model=QuizTriggerResponse)
def create_quiz(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    background_tasks: BackgroundTasks,
    body: Annotated[CreateQuizRequest | None, Body()] = None,
) -> QuizTriggerResponse:
    """복습 문제 생성을 시작한다 (2026-09-01 신규, §5.3⑫).

    복습 탭을 처음 열 때(또는 "다시 생성" 버튼) 프론트가 호출한다 — 요약처럼 세션 처리
    파이프라인에 자동으로 끼워 넣지 않고, 실제로 복습할 때만 LLM을 호출해 비용을 아낀다.
    요약(`detailedNotesMarkdown`)이 아직 없으면 근거 자료가 없어 생성할 수 없다.
    """
    session = _get_session_or_404(db, session_id)
    request = body or CreateQuizRequest()

    has_summary = (
        db.execute(
            select(Summary.id)
            .where(Summary.session_id == session.id, Summary.detailed_notes_markdown != "")
            .limit(1)
        ).first()
        is not None
    )
    if not has_summary:
        raise AppError("SUMMARY_NOT_READY")

    existing = _latest_quiz(db, session.id)
    if existing is not None and existing.status in _QUIZ_ACTIVE_STATUSES:
        raise AppError("INVALID_SESSION_STATE")

    quiz = Quiz(session_id=session.id, status=QuizStatus.GENERATING.value)
    db.add(quiz)
    db.flush()
    db.refresh(quiz)

    background_tasks.add_task(
        generate_quiz_in_background,
        session.id,
        quiz.id,
        llm_provider_name=request.llm_provider,
    )

    return QuizTriggerResponse(
        session_id=session.id,
        status=quiz.status,
        poll_after_seconds=QUIZ_POLL_AFTER_SECONDS,
    )


@router.get("/sessions/{session_id}/quiz", response_model=QuizResponse)
def get_session_quiz(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> QuizResponse:
    """가장 최근에 생성된 복습 문제를 조회한다 (2026-09-01 신규, §5.3⑬).

    아직 한 번도 생성한 적이 없으면 `QUIZ_NOT_FOUND` — 프론트는 이를 "생성 버튼을 보여줄
    시점"으로 해석한다(에러가 아니라 정상적인 초기 상태).
    """
    session = _get_session_or_404(db, session_id)
    quiz = _latest_quiz(db, session.id)
    if quiz is None:
        raise AppError("QUIZ_NOT_FOUND")
    return _quiz_to_response(quiz)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> None:
    """세션 삭제 (§5.3⑧, US-18).

    `sessions`가 삭제되면 `transcripts`/`transcript_segments`/`summaries`는 DB의
    `ON DELETE CASCADE`가 처리한다 (§2.3, `app/models/session.py`의 관계에도
    `passive_deletes=True`로 명시돼 있다). 오디오 파일은 DB 삭제가 (커밋 전이지만) 확실히
    `flush()`된 뒤에 지운다 — DB 삭제가 실패하면 파일은 건드리지 않은 채로 남는다.
    """
    session = _get_session_or_404(db, session_id)
    if session.status in _PROCESSING_STATUSES:
        raise AppError("INVALID_SESSION_STATE")

    audio_path = session.audio_path
    db.delete(session)
    db.flush()

    if audio_path:
        delete_stored_file(audio_path)


EXPORT_MEDIA_TYPES: dict[str, str] = {
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
}


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
    format: Literal["md", "txt", "srt"] = "md",
) -> Response:
    """세션 내보내기 (§5.3⑦, US-16). 허용 목록 외 `format`은 자동으로 400 처리된다."""
    session = _get_session_or_404(db, session_id)

    transcript = db.execute(
        select(Transcript).where(Transcript.session_id == session.id)
    ).scalar_one_or_none()
    if transcript is None:
        raise AppError("TRANSCRIPT_NOT_READY")

    if format == "txt":
        content = render_txt_export(transcript)
    elif format == "srt":
        content = render_srt_export(transcript)
    else:
        latest_summary = db.execute(
            select(Summary)
            .where(Summary.session_id == session.id)
            .order_by(Summary.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        content = render_markdown_export(
            title=session.title,
            course=session.course,
            recorded_at=session.recorded_at,
            transcript=transcript,
            summary=latest_summary,
        )

    filename = build_export_filename(
        recorded_at=session.recorded_at,
        course=session.course,
        title=session.title,
        extension=format,
    )
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": build_content_disposition(filename)},
    )


def _unique_archive_name(filename: str, used: set[str]) -> str:
    """ZIP 안에서 같은 이름이 겹치면 `이름 (2).md`처럼 번호를 붙인다 — 같은 날 같은 제목의
    세션(업로드 기본 제목 "YYYY-MM-DD 수업" 등)이 서로를 덮어쓰지 않게 한다."""
    stem, dot, extension = filename.rpartition(".")
    candidate = filename
    counter = 2
    while candidate in used:
        candidate = f"{stem} ({counter}){dot}{extension}"
        counter += 1
    used.add(candidate)
    return candidate


@router.post("/sessions/export")
def export_sessions_zip(
    body: BulkExportRequest,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> Response:
    """여러 세션의 요약을 세션별 `.md`로 묶은 ZIP 하나로 내려준다 (2026-10-07).

    단건 내보내기(⑦)의 `md`와 달리 전사 전문은 넣지 않는다 — 요약만 모아 보려는 용도다.
    하나라도 없는 세션/요약이 없는 세션이 섞여 있으면 일부만 담긴 ZIP을 주지 않고 통째로
    실패시킨다(받은 사람이 빠진 파일을 알아채기 어렵다).
    """
    session_ids = list(dict.fromkeys(body.session_ids))
    buffer = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for session_id in session_ids:
            session = _get_session_or_404(db, session_id)
            latest_summary = db.execute(
                select(Summary)
                .where(Summary.session_id == session.id)
                .order_by(Summary.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_summary is None:
                raise AppError("SUMMARY_NOT_READY")

            filename = build_export_filename(
                recorded_at=session.recorded_at,
                course=session.course,
                title=session.title,
                extension="md",
            )
            archive.writestr(
                _unique_archive_name(filename, used_names),
                render_markdown_export(
                    title=session.title,
                    course=session.course,
                    recorded_at=session.recorded_at,
                    transcript=None,
                    summary=latest_summary,
                ),
            )

    zip_filename = f"lecture-notes_{datetime.now(UTC):%Y-%m-%d}_{len(session_ids)}건.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": build_content_disposition(zip_filename)},
    )


@router.get("/sessions/{session_id}/audio")
def get_session_audio(
    session_id: str,
    db: Annotated[DBSession, Depends(get_db, scope="function")],
) -> FileResponse:
    """세션 원본 오디오 스트리밍 (T-33, US-21 "세그먼트 클릭 시 해당 시점 오디오 재생").

    §5.2 원 스펙에는 없던 엔드포인트다 — 프론트 세션 상세 화면(T-33)이 `<audio>` 엘리먼트로
    재생·탐색(seek)하려면 오디오 바이트를 내려줄 경로가 반드시 있어야 해서 추가했다.
    `FileResponse`가 `Range` 요청(탐색 시 브라우저가 보냄)을 자동으로 처리해준다 — 직접
    바이트 범위를 파싱할 필요가 없다.
    """
    session = _get_session_or_404(db, session_id)
    if not session.audio_path or not Path(session.audio_path).is_file():
        # §5.2에 없던 엔드포인트라 전용 에러 코드가 없다 — "이 세션에 대해 줄 게 없다"는
        # 의미로 SESSION_NOT_FOUND를 재사용한다(세션 자체는 존재해도 파일이 없을 수 있음:
        # 예를 들어 검증 실패로 롤백된 아주 오래된 레코드).
        raise AppError("SESSION_NOT_FOUND")

    return FileResponse(
        session.audio_path,
        media_type=session.mime_type,
        content_disposition_type="inline",
    )
