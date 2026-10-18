"""GET /api/v1/search 테스트 (T-26, US-15, §3.5, §5.3⑨)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.glossary import GlossaryTerm
from app.models.session import Session
from app.models.summary import Summary
from app.models.transcript import Transcript, TranscriptSegment


def _make_session(**overrides) -> Session:
    defaults = dict(
        title="자료구조 7주차",
        course="자료구조",
        status="DONE",
        source="UPLOAD",
        audio_path="data/audio/dummy.upload",
        original_filename="lecture.m4a",
        mime_type="audio/mp4",
        file_size_bytes=1234,
        duration_seconds=120.0,
        recorded_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Session(**defaults)


def _add_transcript_with_segments(db_session, session: Session, *texts: str) -> Transcript:
    full_text = " ".join(texts)
    transcript = Transcript(
        session_id=session.id,
        text_raw=full_text,
        text_corrected=full_text,
        language="ko",
        provider="fake",
        provider_model="fake-large",
    )
    db_session.add(transcript)
    db_session.flush()
    db_session.add_all(
        [
            TranscriptSegment(
                transcript_id=transcript.id,
                seq=i,
                start_seconds=i * 10.0,
                end_seconds=i * 10.0 + 5.0,
                text=text,
            )
            for i, text in enumerate(texts)
        ]
    )
    db_session.flush()
    return transcript


def _add_summary(
    db_session,
    session: Session,
    *,
    content_markdown: str,
    key_points=None,
    created_at: datetime | None = None,
) -> Summary:
    summary = Summary(
        session_id=session.id,
        content_markdown=content_markdown,
        key_points=key_points or [],
        concepts=[],
        code_snippets=[],
        action_items=[],
        keywords=[],
        provider="fake",
        provider_model="fake-model",
    )
    if created_at is not None:
        summary.created_at = created_at
    db_session.add(summary)
    db_session.flush()
    return summary


class TestSearchValidation:
    def test_missing_query_returns_400(self, client) -> None:
        response = client.get("/api/v1/search")

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_query_shorter_than_2_chars_returns_400(self, client) -> None:
        response = client.get("/api/v1/search", params={"q": "a"})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestSearchTranscript:
    def test_finds_session_by_transcript_content_with_snippet_and_timestamp(
        self, client, db_session
    ) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(
            db_session,
            session,
            "오늘은 이진 탐색 트리에 대해 알아보겠습니다.",
            "먼저 삽입 연산부터 보겠습니다.",
        )

        response = client.get("/api/v1/search", params={"q": "이진 탐색"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["query"] == "이진 탐색"
        assert body["totalCount"] == 1
        result = body["results"][0]
        assert result["sessionId"] == session.id
        assert result["matchedIn"] == "TRANSCRIPT"
        assert "이진 탐색" in result["snippet"]
        assert result["atSeconds"] == 0.0

    def test_no_match_returns_empty_results(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session, "전혀 관련 없는 내용입니다.")

        response = client.get("/api/v1/search", params={"q": "이진 탐색"})

        assert response.status_code == 200, response.text
        assert response.json()["results"] == []
        assert response.json()["totalCount"] == 0

    def test_search_uses_corrected_terminology_for_segments(self, client, db_session) -> None:
        """§3.5: 전사는 보정본 기준으로 찾는다."""
        session = _make_session()
        db_session.add(session)
        db_session.add(GlossaryTerm(term="PostgreSQL", aliases=["포스트그레스큐엘"], course=None))
        db_session.flush()
        transcript = _add_transcript_with_segments(
            db_session, session, "포스트그레스큐엘에서 조인을 하면"
        )
        # 실제 파이프라인(T-23)이라면 저장 시점에 이미 보정됐을 값을 시뮬레이션한다 —
        # transcript_segments.text 자체는 원본 그대로 두는 게 T-23의 결정이므로, 세그먼트가
        # 아니라 이 text_corrected 컬럼을 통해 SQL 후보 필터를 통과해야 한다.
        transcript.text_corrected = "PostgreSQL에서 조인을 하면"
        db_session.flush()

        response = client.get("/api/v1/search", params={"q": "PostgreSQL"})

        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert len(results) == 1
        assert "PostgreSQL" in results[0]["snippet"]

    def test_case_insensitive_match(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session, "FastAPI로 서버를 구현했습니다.")

        response = client.get("/api/v1/search", params={"q": "fastapi"})

        assert response.status_code == 200, response.text
        assert len(response.json()["results"]) == 1

    def test_filters_by_course(self, client, db_session) -> None:
        matching = _make_session(course="자료구조")
        other = _make_session(title="다른 과목", course="네트워크")
        db_session.add_all([matching, other])
        db_session.flush()
        _add_transcript_with_segments(db_session, matching, "이진 탐색 트리 강의")
        _add_transcript_with_segments(db_session, other, "이진 탐색 트리도 언급됨")

        response = client.get("/api/v1/search", params={"q": "이진 탐색", "course": "자료구조"})

        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["sessionId"] == matching.id


class TestSearchSummary:
    def test_finds_session_by_summary_content(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(
            db_session,
            session,
            content_markdown=(
                "## 한 줄 요약\n이진 탐색 트리의 구조와 순회 방식을 다룸.\n\n## 핵심 주제\n없음"
            ),
        )

        response = client.get("/api/v1/search", params={"q": "순회 방식"})

        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["matchedIn"] == "SUMMARY"
        assert "순회 방식" in results[0]["snippet"]

    def test_at_seconds_from_matching_key_point(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_summary(
            db_session,
            session,
            content_markdown="## 한 줄 요약\n중위 순회를 설명함.\n\n## 핵심 주제\n- 중위 순회",
            key_points=[{"text": "중위 순회 개념 설명", "atSeconds": 42.0}],
        )

        response = client.get("/api/v1/search", params={"q": "중위 순회"})

        results = response.json()["results"]
        assert results[0]["atSeconds"] == 42.0

    def test_only_latest_summary_searched(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        now = datetime.now(UTC)
        _add_summary(
            db_session,
            session,
            content_markdown="## 한 줄 요약\n옛날 키워드 포함\n\n## 핵심 주제\n없음",
            created_at=now - timedelta(hours=1),
        )
        _add_summary(
            db_session,
            session,
            content_markdown="## 한 줄 요약\n최신 요약\n\n## 핵심 주제\n없음",
            created_at=now,
        )

        response = client.get("/api/v1/search", params={"q": "옛날 키워드"})

        assert response.json()["results"] == []


class TestSearchTranscriptAndSummaryBothMatch:
    def test_returns_two_results_for_same_session(self, client, db_session) -> None:
        session = _make_session()
        db_session.add(session)
        db_session.flush()
        _add_transcript_with_segments(db_session, session, "이진 탐색 트리 강의 시작합니다.")
        _add_summary(
            db_session,
            session,
            content_markdown="## 한 줄 요약\n이진 탐색 트리를 다룸.\n\n## 핵심 주제\n없음",
        )

        response = client.get("/api/v1/search", params={"q": "이진 탐색"})

        results = response.json()["results"]
        assert len(results) == 2
        matched_in = {r["matchedIn"] for r in results}
        assert matched_in == {"TRANSCRIPT", "SUMMARY"}


class TestSearchOrderingAndLimit:
    def test_sorted_by_recorded_at_desc(self, client, db_session) -> None:
        now = datetime.now(UTC)
        older = _make_session(title="오래된 세션", recorded_at=now - timedelta(days=7))
        newer = _make_session(title="최근 세션", recorded_at=now)
        db_session.add_all([older, newer])
        db_session.flush()
        _add_transcript_with_segments(db_session, older, "검색어 포함된 오래된 강의")
        _add_transcript_with_segments(db_session, newer, "검색어 포함된 최근 강의")

        response = client.get("/api/v1/search", params={"q": "검색어"})

        titles = [r["title"] for r in response.json()["results"]]
        assert titles == ["최근 세션", "오래된 세션"]

    def test_limit_truncates_results_but_total_count_reflects_all(self, client, db_session) -> None:
        for i in range(5):
            session = _make_session(title=f"세션{i}")
            db_session.add(session)
            db_session.flush()
            _add_transcript_with_segments(db_session, session, "검색어 포함된 내용")

        response = client.get("/api/v1/search", params={"q": "검색어", "limit": 2})

        body = response.json()
        assert len(body["results"]) == 2
        assert body["totalCount"] == 5
