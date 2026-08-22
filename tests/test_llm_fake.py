"""`FakeLlmProvider` 동작 검증 (T-14)."""

from __future__ import annotations

import json

from app.core.errors import AppError
from app.llm.fake import DEFAULT_VALID_SUMMARY_JSON, FakeLlmProvider, make_summary_json


class TestFakeLlmProviderIdentity:
    def test_provider_name_and_model(self) -> None:
        provider = FakeLlmProvider(provider_model="fake-qwen3")
        assert provider.provider_name == "fake"
        assert provider.provider_model == "fake-qwen3"


class TestFakeLlmProviderDefaultResponse:
    def test_default_response_is_valid_summary_json(self) -> None:
        provider = FakeLlmProvider()
        result = provider.generate("아무 프롬프트")

        assert result == DEFAULT_VALID_SUMMARY_JSON
        data = json.loads(result)
        assert "oneLineSummary" in data
        assert data["actionItems"] == []

    def test_records_calls(self) -> None:
        provider = FakeLlmProvider()
        provider.generate("prompt-1")
        provider.generate("prompt-2")

        assert provider.calls == ["prompt-1", "prompt-2"]


class TestFakeLlmProviderScenarios:
    def test_sequential_responses_advance_per_call(self) -> None:
        provider = FakeLlmProvider(responses=["first", "second", "third"])

        assert provider.generate("p") == "first"
        assert provider.generate("p") == "second"
        assert provider.generate("p") == "third"
        # 목록이 소진되면 마지막 항목을 반복한다.
        assert provider.generate("p") == "third"

    def test_quota_exceeded_scenario(self) -> None:
        provider = FakeLlmProvider(responses=[AppError("LLM_QUOTA_EXCEEDED", retryable=True)])

        try:
            provider.generate("p")
            raised = False
        except AppError as exc:
            raised = True
            assert exc.code == "LLM_QUOTA_EXCEEDED"
            assert exc.retryable is True
        assert raised

    def test_timeout_scenario(self) -> None:
        provider = FakeLlmProvider(responses=[TimeoutError("llm timed out")])

        try:
            provider.generate("p")
            raised = False
        except TimeoutError:
            raised = True
        assert raised

    def test_malformed_response_then_valid_response(self) -> None:
        """형식위반 시나리오: 1차 응답은 JSON이 아니고, 2차 응답은 유효하다 (T-16 재요청 검증용)."""
        provider = FakeLlmProvider(responses=["이것은 JSON이 아닙니다", DEFAULT_VALID_SUMMARY_JSON])

        first = provider.generate("p")
        second = provider.generate("p")

        assert first == "이것은 JSON이 아닙니다"
        assert second == DEFAULT_VALID_SUMMARY_JSON


class TestMakeSummaryJsonHelper:
    def test_overrides_action_items(self) -> None:
        text = make_summary_json(actionItems=[{"text": "과제 3번 제출", "dueDate": "2026-08-27"}])
        data = json.loads(text)

        assert data["actionItems"] == [{"text": "과제 3번 제출", "dueDate": "2026-08-27"}]
        # 다른 필드는 기본값 그대로 유지된다.
        assert "oneLineSummary" in data
