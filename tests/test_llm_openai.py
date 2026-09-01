"""OpenAI Responses API 구현체 테스트 (2026-08-29).

실제 네트워크/OpenAI 서버를 띄우지 않고 `client.responses.create`를 monkeypatch해
결정론적으로 검증한다 (§6 테스트성 NFR: 전체 스위트가 외부 API를 호출하지 않아야 한다).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.core.errors import AppError
from app.llm.openai_provider import OpenAiLlmProvider

_REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def _status_error(cls: type[openai.APIStatusError], status_code: int) -> openai.APIStatusError:
    response = httpx2.Response(status_code, request=_REQUEST)
    return cls("boom", response=response, body=None)


class TestOpenAiLlmProviderIdentity:
    def test_provider_name_and_model(self) -> None:
        provider = OpenAiLlmProvider(api_key="sk-test", model="gpt-4o-mini")
        assert provider.provider_name == "openai"
        assert provider.provider_model == "gpt-4o-mini"


class TestOpenAiLlmProviderRequestShape:
    def test_sends_expected_request_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_create(*, model: str, input: str, text: dict):
            captured["model"] = model
            captured["input"] = input
            captured["text"] = text
            return SimpleNamespace(output_text="{}")

        provider = OpenAiLlmProvider(api_key="sk-test", model="gpt-4o-mini")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        provider.generate("요약해줘")

        assert captured["model"] == "gpt-4o-mini"
        assert captured["input"] == "요약해줘"
        fmt = captured["text"]["format"]
        assert fmt["type"] == "json_schema"
        assert fmt["strict"] is True
        schema = fmt["schema"]
        assert set(schema["required"]) == {
            "suggestedTitle",
            "oneLineSummary",
            "keyPoints",
            "detailedNotes",
        }
        assert schema["additionalProperties"] is False

    def test_uses_explicit_response_schema_when_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2026-09-01: `response_schema`를 넘기면 요약용 기본 스키마 대신 그걸 쓴다 — 복습
        문제(`app/llm/quiz_generator.py`)처럼 출력 모양이 다른 호출부를 지원하기 위함."""
        captured: dict = {}

        def fake_create(*, model: str, input: str, text: dict):
            captured["text"] = text
            return SimpleNamespace(output_text="{}")

        provider = OpenAiLlmProvider(api_key="sk-test", model="gpt-4o-mini")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        custom_schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        provider.generate(
            "복습 문제 만들어줘",
            response_schema=custom_schema,
            response_schema_name="lecture_quiz",
        )

        fmt = captured["text"]["format"]
        assert fmt["name"] == "lecture_quiz"
        assert fmt["schema"] is custom_schema


class TestOpenAiLlmProviderSuccess:
    def test_returns_output_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps({"oneLineSummary": "요약"})

        def fake_create(*, model: str, input: str, text: dict):
            return SimpleNamespace(output_text=payload)

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        result = provider.generate("prompt")

        assert result == payload


class TestOpenAiLlmProviderErrorMapping:
    def test_authentication_error_maps_to_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            raise _status_error(openai.AuthenticationError, 401)

        provider = OpenAiLlmProvider(api_key="bad-key")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_NOT_CONFIGURED"
        assert exc_info.value.retryable is False

    def test_rate_limit_error_maps_to_quota_exceeded_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            raise _status_error(openai.RateLimitError, 429)

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_QUOTA_EXCEEDED"
        assert exc_info.value.retryable is True

    def test_internal_server_error_maps_to_llm_failed_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            raise _status_error(openai.InternalServerError, 500)

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is True

    def test_connection_error_maps_to_llm_failed_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            raise openai.APIConnectionError(request=_REQUEST)

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is True

    def test_timeout_error_maps_to_llm_failed_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            raise openai.APITimeoutError(request=_REQUEST)

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is True

    def test_bad_request_error_maps_to_llm_failed_not_retryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            raise _status_error(openai.BadRequestError, 400)

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_FAILED"
        assert exc_info.value.retryable is False

    def test_empty_output_text_is_invalid_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_create(*, model: str, input: str, text: dict):
            return SimpleNamespace(output_text="")

        provider = OpenAiLlmProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client.responses, "create", fake_create)

        with pytest.raises(AppError) as exc_info:
            provider.generate("prompt")

        assert exc_info.value.code == "LLM_INVALID_RESPONSE"
