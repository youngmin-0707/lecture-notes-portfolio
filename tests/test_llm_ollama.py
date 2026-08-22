"""로컬 Ollama HTTP API 구현체 테스트 (T-17, US-09).

실제 네트워크/Ollama 서버를 띄우지 않고 `httpx.post`를 monkeypatch해 결정론적으로 검증한다
(§6 테스트성 NFR: 전체 스위트가 외부 API를 호출하지 않아야 한다).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import AppError
from app.llm.ollama import OllamaLlmProvider


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}

    def json(self) -> dict:
        return self._json_body


class TestOllamaLlmProviderIdentity:
    def test_provider_name_and_model(self) -> None:
        provider = OllamaLlmProvider(model="qwen3:8b")
        assert provider.provider_name == "ollama"
        assert provider.provider_model == "qwen3:8b"


class TestOllamaLlmProviderRequestShape:
    def test_sends_expected_payload_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _FakeResponse(200, {"response": "{}", "done": True})

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider(
            base_url="http://127.0.0.1:11434",
            model="qwen3:8b",
            keep_alive="30s",
            num_ctx=8192,
            timeout_seconds=600,
        )
        provider.generate("요약해줘")

        assert captured["url"] == "http://127.0.0.1:11434/api/generate"
        body = captured["json"]
        assert body["model"] == "qwen3:8b"
        assert body["prompt"] == "요약해줘"
        assert body["stream"] is False
        assert body["think"] is False
        assert body["format"] == "json"
        assert body["keep_alive"] == "30s"
        assert body["options"]["num_ctx"] == 8192
        assert captured["timeout"] == 600


class TestOllamaLlmProviderSuccess:
    def test_returns_response_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"oneLineSummary": "요약"})

        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse(200, {"response": payload, "done": True})

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        result = provider.generate("prompt")

        assert result == payload


class TestOllamaLlmProviderErrorMapping:
    def test_connect_error_maps_to_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(url: str, *, json: dict, timeout: float):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_NOT_CONFIGURED"
        assert exc_info.value.retryable is False

    def test_timeout_maps_to_llm_failed_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(url: str, *, json: dict, timeout: float):
            raise httpx.ReadTimeout("timed out")

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is True

    def test_429_maps_to_quota_exceeded_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse(429)

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_QUOTA_EXCEEDED"
        assert exc_info.value.retryable is True

    def test_500_maps_to_llm_failed_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse(500)

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is True

    def test_400_maps_to_llm_failed_not_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse(400)

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is False

    def test_404_maps_to_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse(404)

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_NOT_CONFIGURED"

    def test_response_missing_text_field_is_invalid_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_post(url: str, *, json: dict, timeout: float) -> _FakeResponse:
            return _FakeResponse(200, {"done": True})  # "response" 필드 없음

        monkeypatch.setattr("app.llm.ollama.httpx.post", fake_post)

        provider = OllamaLlmProvider()
        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_INVALID_RESPONSE"
