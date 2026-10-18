"""용어집 API 테스트 (T-22, §5.3 ⑩)."""

from __future__ import annotations

from app.models.glossary import GlossaryTerm


class TestListGlossaryTerms:
    def test_list_empty_glossary_returns_empty_items(self, client) -> None:
        response = client.get("/api/v1/glossary")

        assert response.status_code == 200, response.text
        assert response.json() == {"items": []}

    def test_list_returns_created_terms_sorted_by_term(self, client, db_session) -> None:
        db_session.add_all(
            [
                GlossaryTerm(term="PostgreSQL", aliases=["포스트그레"], course=None),
                GlossaryTerm(term="Docker", aliases=["도커"], course=None),
            ]
        )
        db_session.flush()

        response = client.get("/api/v1/glossary")

        assert response.status_code == 200, response.text
        terms = [item["term"] for item in response.json()["items"]]
        assert terms == sorted(terms)
        assert set(terms) == {"PostgreSQL", "Docker"}

    def test_list_filters_by_course_including_global_terms(self, client, db_session) -> None:
        db_session.add_all(
            [
                GlossaryTerm(term="전역용어", aliases=[], course=None),
                GlossaryTerm(term="자료구조전용", aliases=[], course="자료구조"),
                GlossaryTerm(term="네트워크전용", aliases=[], course="네트워크"),
            ]
        )
        db_session.flush()

        response = client.get("/api/v1/glossary", params={"course": "자료구조"})

        assert response.status_code == 200, response.text
        terms = {item["term"] for item in response.json()["items"]}
        assert terms == {"전역용어", "자료구조전용"}


class TestCreateGlossaryTerm:
    def test_create_term_201_and_persisted(self, client, db_session) -> None:
        response = client.post(
            "/api/v1/glossary",
            json={"term": "PostgreSQL", "aliases": ["포스트그레스큐엘", "포스트그레"]},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["term"] == "PostgreSQL"
        assert body["aliases"] == ["포스트그레스큐엘", "포스트그레"]
        assert body["course"] is None
        assert "id" in body

        stored = db_session.get(GlossaryTerm, body["id"])
        assert stored is not None
        assert stored.term == "PostgreSQL"

    def test_create_term_with_course(self, client) -> None:
        response = client.post(
            "/api/v1/glossary",
            json={"term": "이진 탐색 트리", "aliases": ["비에스티"], "course": "자료구조"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["course"] == "자료구조"

    def test_create_term_defaults_aliases_to_empty_list(self, client) -> None:
        response = client.post("/api/v1/glossary", json={"term": "상속"})

        assert response.status_code == 201, response.text
        assert response.json()["aliases"] == []

    def test_create_term_missing_term_400(self, client) -> None:
        response = client.post("/api/v1/glossary", json={"aliases": ["포스트그레"]})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_create_term_aliases_not_array_400(self, client) -> None:
        response = client.post(
            "/api/v1/glossary", json={"term": "PostgreSQL", "aliases": "포스트그레"}
        )

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_create_term_too_long_400(self, client) -> None:
        response = client.post("/api/v1/glossary", json={"term": "a" * 101})

        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestDeleteGlossaryTerm:
    def test_delete_existing_term_204_and_removed(self, client, db_session) -> None:
        term = GlossaryTerm(term="Redis", aliases=["레디스"], course=None)
        db_session.add(term)
        db_session.flush()
        db_session.refresh(term)

        response = client.delete(f"/api/v1/glossary/{term.id}")

        assert response.status_code == 204, response.text
        assert db_session.get(GlossaryTerm, term.id) is None

    def test_delete_missing_term_404(self, client) -> None:
        response = client.delete("/api/v1/glossary/999999")

        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "NOT_FOUND"
