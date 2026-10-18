"""형식 위반 시 1회 재요청 로직 테스트 (T-16, §3.4)."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.llm.fake import DEFAULT_VALID_SUMMARY_JSON, FakeLlmProvider
from app.llm.summarizer import generate_structured_summary


class TestGenerateStructuredSummarySuccess:
    def test_succeeds_on_first_valid_response(self) -> None:
        provider = FakeLlmProvider(responses=[DEFAULT_VALID_SUMMARY_JSON])

        parsed = generate_structured_summary(provider, "prompt")

        assert parsed.one_line_summary
        assert len(provider.calls) == 1


class TestGenerateStructuredSummaryRetriesOnceOnFormatViolation:
    def test_retries_once_and_succeeds(self) -> None:
        provider = FakeLlmProvider(responses=["이것은 JSON이 아닙니다", DEFAULT_VALID_SUMMARY_JSON])

        parsed = generate_structured_summary(provider, "prompt")

        assert parsed.one_line_summary
        assert len(provider.calls) == 2
        # 재요청 프롬프트는 원본 프롬프트를 포함하되 실패 이유를 덧붙인다.
        assert "prompt" in provider.calls[1]
        assert provider.calls[1] != provider.calls[0]

    def test_raises_llm_invalid_response_after_second_failure(self) -> None:
        provider = FakeLlmProvider(responses=["여전히 JSON이 아닙니다", "이번에도 아닙니다"])

        with pytest.raises(AppError) as exc_info:
            generate_structured_summary(provider, "prompt")

        assert exc_info.value.code == "LLM_INVALID_RESPONSE"
        assert exc_info.value.retryable is False
        # 형식위반 재요청은 정확히 1회만 이루어진다 (원 요청 + 재요청 = 2회 호출).
        assert len(provider.calls) == 2


class TestGenerateStructuredSummaryPropagatesTransientErrors:
    def test_propagates_quota_exceeded_without_retrying_format(self) -> None:
        error = AppError("LLM_QUOTA_EXCEEDED", retryable=True)
        provider = FakeLlmProvider(responses=[error])

        with pytest.raises(AppError) as exc_info:
            generate_structured_summary(provider, "prompt")

        assert exc_info.value.code == "LLM_QUOTA_EXCEEDED"
        assert exc_info.value.retryable is True
        assert len(provider.calls) == 1
