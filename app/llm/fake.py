"""`LlmProvider`의 결정론적 Fake 구현체 (T-14).

실제 Ollama를 호출하지 않고 정상/429/타임아웃/형식위반 시나리오를 생성자 인자로 주입해
재현할 수 있다. `pipeline/`·API 테스트는 이 Fake를 사용해 실제 모델 없이 수 초 안에 전체
흐름을 검증한다 (§6 테스트성 NFR).
"""

from __future__ import annotations

import json

from app.llm.base import LlmProvider

# 파서(§3.4 §T-16, 2026-08-29 자유형식 본문 도입으로 개정)가 요구하는 최소 필드를 모두 채운,
# 항상 파싱에 성공하는 기본 응답.
DEFAULT_VALID_SUMMARY_JSON = json.dumps(
    {
        "suggestedTitle": "이진 탐색 트리 삽입/탐색 구현",
        "oneLineSummary": "이진 탐색 트리의 구조와 삽입·탐색 연산을 다룬 강의입니다.",
        "keyPoints": [
            {"text": "이진 탐색 트리(BST)의 정의와 특성", "atSeconds": 12.0},
            {"text": "BST 삽입 연산의 재귀적 구현", "atSeconds": 240.0},
            {"text": "평균/최악 시간 복잡도 비교", "atSeconds": 480.0},
        ],
        "keywords": ["이진 탐색 트리", "중위 순회", "시간 복잡도"],
        "detailedNotes": (
            "1. 이진 탐색 트리(BST)\n"
            "왼쪽 서브트리 < 루트 < 오른쪽 서브트리 규칙을 만족하는 트리입니다.\n\n"
            "2. 중위 순회\n"
            "왼쪽 → 루트 → 오른쪽 순서로 방문하면 정렬된 순서를 얻습니다.\n\n"
            "```python\n"
            "def insert(node, value):\n"
            "    if node is None:\n"
            "        return Node(value)\n"
            "    ...\n"
            "```"
        ),
    },
    ensure_ascii=False,
)


def make_summary_json(**overrides: object) -> str:
    """`DEFAULT_VALID_SUMMARY_JSON`을 베이스로 일부 필드만 덮어써 JSON 문자열을 만든다.

    테스트에서 "과제/공지가 있는 경우", "형식이 깨진 응답" 등 시나리오를 손쉽게 구성할 때 쓴다.
    """
    data = json.loads(DEFAULT_VALID_SUMMARY_JSON)
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class FakeLlmProvider(LlmProvider):
    """정상/429/타임아웃/형식위반을 결정론적으로 재현하는 Fake `LlmProvider`.

    Args:
        responses: `generate()` 호출마다 순서대로 반환/발생시킬 값의 목록. 각 항목은
            `str`(응답 원문) 또는 `BaseException`(그 시점에 던질 예외) 중 하나다.
            호출 횟수가 목록 길이를 넘어서면 마지막 항목을 반복한다.
            미지정 시 항상 `DEFAULT_VALID_SUMMARY_JSON`을 반환한다.
        provider_model: `summaries.provider_model`에 저장될 값.
        provider_name: `summaries.provider`에 저장될 값. provider별 분기(예: OpenAI만 다른
            map-reduce 청크 크기를 쓰는 `_default_chunk_size_tokens`)를 테스트할 때 `"openai"`
            등으로 지정한다.
    """

    def __init__(
        self,
        *,
        responses: list[str | BaseException] | None = None,
        provider_model: str = "fake-llm-model",
        provider_name: str = "fake",
    ) -> None:
        self._responses: list[str | BaseException] = (
            list(responses) if responses is not None else [DEFAULT_VALID_SUMMARY_JSON]
        )
        if not self._responses:
            raise ValueError("responses는 비어 있을 수 없습니다.")
        self._provider_model = provider_model
        self._provider_name = provider_name
        self._call_index = 0
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def provider_model(self) -> str:
        return self._provider_model

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        index = min(self._call_index, len(self._responses) - 1)
        item = self._responses[index]
        self._call_index += 1

        if isinstance(item, BaseException):
            raise item
        return item
