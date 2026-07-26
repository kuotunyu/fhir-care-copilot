"""OpenAI adapter 的離線測試——**不打任何 API**。

跟 ``test_providers_gemini.py`` 同一個理由:這兩個 adapter 只在打真 API 時
才會被執行,而 CI 一律用 mock provider(secret 永不進 CI,這是對的)。結果就是
**送出去的請求形狀在自動化裡完全沒被覆蓋**——gemini adapter 因此藏了一個
``role="tool"`` 的 bug,直到換模型打真 API 才炸出來。

這裡用假 client 把送出去的參數攔下來,檢查會靜靜壞掉的那幾件事:
工具結果的形狀、``call_id`` 有沒有正確對回去、多輪有沒有串上
``previous_response_id``。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from fhir_copilot.providers.base import ToolCallOutcome
from fhir_copilot.providers.openai_provider import OpenAIProvider, _OpenAIState


class FakeResponses:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return _FakeResponse()


class _FakeResponse:
    id = "resp_fake_1"
    output: list[Any] = []  # noqa: RUF012 - 假回應,不需要 ClassVar 語意
    output_text = "假的最終回答"
    usage = None


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.fixture
def provider() -> OpenAIProvider:
    instance = OpenAIProvider(model_id="gpt-5.4-mini", api_key="fake-key-not-used")
    instance._client = FakeClient()  # type: ignore[assignment]
    return instance


def _state() -> _OpenAIState:
    return _OpenAIState(previous_response_id="resp_previous", tool_specs=())


def test_tool_result_uses_the_function_call_output_shape(provider: OpenAIProvider) -> None:
    """Responses API 收工具結果的形狀是 ``function_call_output``,不是 chat 的 role 訊息。

    寫錯的話 SDK 不一定會擋,但模型收不到工具結果——症狀是「模型無視工具、開始瞎掰」,
    而不是明顯的例外。
    """
    provider.continue_with_tool_results(
        _state(),
        [
            ToolCallOutcome(
                call_id="call_abc", tool_name="list_active_conditions", output={"ok": True}
            )
        ],
    )

    items = provider._client.responses.last_kwargs["input"]  # type: ignore[attr-defined]
    assert len(items) == 1
    assert items[0]["type"] == "function_call_output"
    assert items[0]["call_id"] == "call_abc", "call_id 必須原樣傳回,否則對不回是哪個工具呼叫"


def test_tool_output_is_json_encoded_without_ascii_escaping(provider: OpenAIProvider) -> None:
    """``output`` 必須是字串;中文不要被跳脫成 \\uXXXX(那會白白吃掉 token)。"""
    provider.continue_with_tool_results(
        _state(),
        [ToolCallOutcome(call_id="c1", tool_name="t", output={"診斷": "高血壓"})],
    )

    raw = provider._client.responses.last_kwargs["input"][0]["output"]  # type: ignore[attr-defined]
    assert isinstance(raw, str)
    assert "高血壓" in raw, "ensure_ascii 沒關掉,中文被跳脫了"
    assert json.loads(raw) == {"診斷": "高血壓"}


def test_multi_turn_threads_the_previous_response_id(provider: OpenAIProvider) -> None:
    """多輪靠 ``previous_response_id`` 串接。斷掉的話模型會失憶,但不會報錯。"""
    provider.continue_with_tool_results(
        _state(), [ToolCallOutcome(call_id="c1", tool_name="t", output={})]
    )

    kwargs = provider._client.responses.last_kwargs  # type: ignore[attr-defined]
    assert kwargs["previous_response_id"] == "resp_previous"


def test_tools_are_resent_every_turn(provider: OpenAIProvider) -> None:
    """工具清單每一輪都要重送——Responses API 不會從前一輪繼承。"""
    provider.start(system_prompt="系統提示", user_message="問題", tool_specs=())
    assert "tools" in provider._client.responses.last_kwargs  # type: ignore[attr-defined]

    provider.continue_with_tool_results(
        _state(), [ToolCallOutcome(call_id="c1", tool_name="t", output={})]
    )
    assert "tools" in provider._client.responses.last_kwargs  # type: ignore[attr-defined]
