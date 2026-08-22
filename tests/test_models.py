"""ORM 모델 단위 테스트 (T-04, §2.3).

`db_session`(PostgreSQL, SAVEPOINT 격리)과 sqlite in-memory 양쪽에서 핵심 제약(FK CASCADE,
UNIQUE)이 동일하게 동작하는지 확인한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.db.base import Base
from app.models import GlossaryTerm, Session, Summary, Transcript, TranscriptSegment


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status="UPLOADED",
        source="UPLOAD",
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


@pytest.fixture()
def sqlite_session() -> Iterator[DBSession]:
    engine = create_engine("sqlite:///:memory:", future=True)

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = DBSession(bind=engine)
    yield session
    session.close()
    engine.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_session_crud_and_cascade_delete(
    backend: str, sqlite_session: DBSession, db_session: DBSession
) -> None:
    db = sqlite_session if backend == "sqlite" else db_session

    session = _make_session()
    db.add(session)
    db.flush()

    transcript = Transcript(
        session_id=session.id,
        text_raw="원본 전사",
        text_corrected="보정 전사",
        language="ko",
        provider="local_whisper",
        provider_model="large-v3-turbo",
    )
    db.add(transcript)
    db.flush()

    db.add_all(
        [
            TranscriptSegment(
                transcript_id=transcript.id, seq=0, start_seconds=0.0, end_seconds=5.0, text="a"
            ),
            TranscriptSegment(
                transcript_id=transcript.id, seq=1, start_seconds=5.0, end_seconds=9.0, text="b"
            ),
        ]
    )
    db.add(
        Summary(
            session_id=session.id,
            content_markdown="## 한 줄 요약\n내용",
            key_points=[{"text": "핵심", "atSeconds": 1.0}],
            concepts=[],
            code_snippets=[],
            action_items=[],
            keywords=["키워드"],
            provider="ollama",
            provider_model="qwen3:14b",
        )
    )
    db.flush()

    assert db.get(Session, session.id) is not None
    assert len(transcript.segments) == 2

    # ON DELETE CASCADE: 세션 삭제 시 transcript/segments/summaries 모두 삭제된다.
    # `passive_deletes=True`이므로 ORM이 자식을 미리 로드해 DELETE를 발행하지 않고 DB의
    # ON DELETE CASCADE에 위임한다. identity map에 남은 (이제 삭제된) 인스턴스를 건드리면
    # `ObjectDeletedError`가 나므로, 컬럼만 선택하는 스칼라 count 쿼리로 DB 상태를 직접 확인한다.
    transcript_id = transcript.id
    db.delete(session)
    db.flush()

    transcript_count = db.execute(
        select(func.count()).select_from(Transcript).where(Transcript.id == transcript_id)
    ).scalar_one()
    segment_count = db.execute(
        select(func.count())
        .select_from(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript_id)
    ).scalar_one()
    summary_count = db.execute(
        select(func.count()).select_from(Summary).where(Summary.session_id == session.id)
    ).scalar_one()

    assert transcript_count == 0
    assert segment_count == 0
    assert summary_count == 0


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_transcript_session_id_is_unique(
    backend: str, sqlite_session: DBSession, db_session: DBSession
) -> None:
    db = sqlite_session if backend == "sqlite" else db_session

    session = _make_session()
    db.add(session)
    db.flush()

    db.add(
        Transcript(
            session_id=session.id,
            text_raw="첫 번째",
            language="ko",
            provider="local_whisper",
            provider_model="large-v3-turbo",
        )
    )
    db.flush()

    db.add(
        Transcript(
            session_id=session.id,
            text_raw="두 번째(중복이라 실패해야 함)",
            language="ko",
            provider="local_whisper",
            provider_model="large-v3-turbo",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_transcript_segment_seq_unique_per_transcript(
    backend: str, sqlite_session: DBSession, db_session: DBSession
) -> None:
    db = sqlite_session if backend == "sqlite" else db_session

    session = _make_session()
    db.add(session)
    db.flush()
    transcript = Transcript(
        session_id=session.id,
        text_raw="원본",
        language="ko",
        provider="local_whisper",
        provider_model="large-v3-turbo",
    )
    db.add(transcript)
    db.flush()

    db.add(
        TranscriptSegment(
            transcript_id=transcript.id, seq=0, start_seconds=0, end_seconds=1, text="x"
        )
    )
    db.flush()
    db.add(
        TranscriptSegment(
            transcript_id=transcript.id, seq=0, start_seconds=1, end_seconds=2, text="y"
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_session_allows_multiple_summaries(sqlite_session: DBSession) -> None:
    db = sqlite_session
    session = _make_session()
    db.add(session)
    db.flush()

    db.add(
        Summary(
            session_id=session.id,
            content_markdown="첫 번째 요약",
            provider="ollama",
            provider_model="qwen3:14b",
        )
    )
    db.add(
        Summary(
            session_id=session.id,
            content_markdown="재요약",
            provider="gemini",
            provider_model="gemini-2.5-flash",
        )
    )
    db.flush()

    assert db.query(Summary).filter_by(session_id=session.id).count() == 2


def test_glossary_term_defaults(sqlite_session: DBSession) -> None:
    db = sqlite_session
    term = GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘", "포스트그레"], course=None)
    db.add(term)
    db.flush()

    fetched = db.get(GlossaryTerm, term.id)
    assert fetched is not None
    assert fetched.aliases == ["포스트그레스큐엘", "포스트그레"]
    assert fetched.course is None
