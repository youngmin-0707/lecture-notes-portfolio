"""GET /health 테스트 (T-28, §5.3⑫, §6 보안/관측성)."""

from __future__ import annotations

import httpx
import pytest

from app.api.v1 import health as health_module
from app.core.config import settings


class TestHealthSchema:
    def test_returns_200_with_expected_shape(self, real_client) -> None:
        response = real_client.get("/health")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] in ("ok", "degraded")
        checks = body["checks"]
        assert set(checks) == {
            "database",
            "diskFreeBytes",
            "stt",
            "llm",
            "offlineMode",
            "bindHost",
        }
        assert isinstance(checks["database"]["ok"], bool)
        assert isinstance(checks["diskFreeBytes"]["value"], int)
        assert checks["stt"]["provider"] == settings.STT_PROVIDER
        assert checks["stt"]["model"] == settings.STT_MODEL
        assert isinstance(checks["stt"]["modelCached"], bool)
        assert checks["llm"]["provider"] == settings.LLM_PROVIDER
        assert checks["bindHost"] == settings.BIND_HOST

    def test_database_ok_when_reachable(self, real_client) -> None:
        response = real_client.get("/health")

        assert response.json()["checks"]["database"]["ok"] is True


class TestHealthNeverExposesApiKeys:
    def test_gemini_and_groq_keys_not_in_response_body(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "super-secret-gemini-key")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "super-secret-groq-key")

        response = real_client.get("/health")

        assert "super-secret-gemini-key" not in response.text
        assert "super-secret-groq-key" not in response.text

    def test_llm_check_only_exposes_configured_boolean(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
        monkeypatch.setattr(settings, "GEMINI_API_KEY", "super-secret-gemini-key")

        response = real_client.get("/health")

        llm_check = response.json()["checks"]["llm"]
        assert llm_check["configured"] is True
        assert "key" not in str(llm_check).lower()
        assert "super-secret-gemini-key" not in response.text


class TestHealthOpenAiProvider:
    def test_configured_true_when_api_key_set_and_exposes_openai_model(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-super-secret")
        monkeypatch.setattr(settings, "OPENAI_MODEL", "gpt-4o-mini")

        response = real_client.get("/health")

        llm_check = response.json()["checks"]["llm"]
        assert llm_check["provider"] == "openai"
        assert llm_check["model"] == "gpt-4o-mini"
        assert llm_check["configured"] is True
        assert llm_check["reachable"] is None
        assert "sk-super-secret" not in response.text

    def test_configured_false_when_api_key_missing(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

        response = real_client.get("/health")

        body = response.json()
        assert body["checks"]["llm"]["configured"] is False
        assert body["status"] == "degraded"

    def test_openai_provider_is_never_offline_mode(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "STT_PROVIDER", "local_whisper")
        monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-super-secret")

        response = real_client.get("/health")

        assert response.json()["checks"]["offlineMode"] is False


class TestHealthDegradesGracefully:
    def test_llm_unreachable_marks_degraded_but_still_200(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 로컬 .env가 LLM_PROVIDER=openai로 바뀌어도 이 테스트는 ollama 분기를 검증해야 하므로
        # 명시적으로 고정한다 — 테스트가 개발자의 실제 .env에 의존하면 안 된다.
        monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
        monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:1")

        response = real_client.get("/health")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["llm"]["ok"] is False
        assert body["checks"]["llm"]["reachable"] is False

    def test_llm_reachable_marks_ok(self, real_client, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

        def _fake_get(url, timeout):
            class _Resp:
                status_code = 200

            return _Resp()

        monkeypatch.setattr(httpx, "get", _fake_get)

        response = real_client.get("/health")

        assert response.json()["checks"]["llm"]["reachable"] is True

    def test_database_failure_marks_degraded_not_500(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_check_database`가 내부적으로 예외를 잡아 degraded로 표현하는지 확인한다.

        `text()` 자체가 터지게 해서 `_check_database`의 실제 try/except 경로를 그대로
        통과시킨다 (함수를 통째로 갈아치우면 그 try/except를 우회해버려 의미가 없다).
        """

        def _boom(*_args, **_kwargs):
            raise RuntimeError("db is down")

        monkeypatch.setattr(health_module, "text", _boom)

        response = real_client.get("/health")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"]["ok"] is False


class TestHealthOfflineMode:
    def test_offline_mode_true_for_local_whisper_and_ollama(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "STT_PROVIDER", "local_whisper")
        monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

        response = real_client.get("/health")

        assert response.json()["checks"]["offlineMode"] is True

    def test_offline_mode_false_when_llm_provider_is_cloud(
        self, real_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

        response = real_client.get("/health")

        assert response.json()["checks"]["offlineMode"] is False
