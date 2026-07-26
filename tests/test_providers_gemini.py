"""Gemini adapter 的離線測試——**不打任何 API**。

這個檔案存在的理由是一次真實的 bug:工具結果原本用 ``role="tool"`` 送回去,
`gemini-3.1-flash-lite` 容忍了它,`gemini-3.5-flash-lite` 直接回
``400 INVALID_ARGUMENT: Role 'tool' is not supported``。

那個容忍是運氣不是正確,而**它只有在打真的 API 時才會現形**——這個 adapter
當時一個單元測試都沒有。用假 client 把送出去的請求攔下來檢查,就不必花錢
也不必等到換模型才知道。
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from fhir_copilot.providers.base import ToolCallOutcome
from fhir_copilot.providers.gemini import GeminiProvider

# Gemini API 接受的角色,逐字取自 3.5 回的錯誤訊息。**沒有 tool。**
# (原訊息把 USER 列了兩次,這裡去重。)
LEGAL_ROLES = frozenset(
    {"SYSTEM", "SYSTEM_1", "USER", "ASSISTANT", "DEVELOPER", "CONTEXT", "USER_CONTEXT", "MODEL"}
)


class FakeModels:
    """把送出去的 contents 攔下來,回一個沒有 function call 的最小回應。"""

    def __init__(self) -> None:
        self.last_contents: list[Any] = []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.last_contents = list(contents)
        return _FakeResponse()


class _FakeResponse:
    function_calls: ClassVar[list[Any]] = []
    candidates: ClassVar[list[Any]] = []
    text = "假的最終回答"
    usage_metadata = None


class FakeClient:
    def __init__(self) -> None:
        self.models = FakeModels()


@pytest.fixture
def provider() -> GeminiProvider:
    instance = GeminiProvider(model_id="gemini-3.5-flash-lite", api_key="fake-key-not-used")
    instance._client = FakeClient()  # type: ignore[assignment]
    return instance


class _State:
    def __init__(self) -> None:
        self.history: list[Any] = []
        self.tool_specs: tuple[Any, ...] = ()


def test_function_response_role_is_legal(provider: GeminiProvider) -> None:
    """**這是那個 bug 的回歸測試。** ``tool`` 不在合法角色裡。"""
    provider.continue_with_tool_results(
        _State(),
        [ToolCallOutcome(call_id="c1", tool_name="list_active_conditions", output={"ok": True})],
    )

    sent = provider._client.models.last_contents  # type: ignore[attr-defined]
    assert len(sent) == 1
    role = sent[0].role
    assert role.upper() in LEGAL_ROLES, f"Gemini 不接受 role={role!r}"
    assert role == "user", "function response 屬於使用者這一側,不是獨立的 tool 角色"


def test_start_sends_the_user_message_as_user_role(provider: GeminiProvider) -> None:
    provider.start(system_prompt="系統提示", user_message="問題", tool_specs=())

    sent = provider._client.models.last_contents  # type: ignore[attr-defined]
    assert [c.role for c in sent] == ["user"]


def test_every_content_role_is_legal_across_a_full_round(provider: GeminiProvider) -> None:
    """整輪走完之後,history 裡**每一個** Content 的角色都要合法。

    只檢查最後一個的話,history 前面累積的角色壞掉會漏掉。
    """
    provider.start(system_prompt="系統提示", user_message="問題", tool_specs=())
    state = _State()
    state.history = list(provider._client.models.last_contents)  # type: ignore[attr-defined]

    provider.continue_with_tool_results(
        state,
        [ToolCallOutcome(call_id="c1", tool_name="get_patient_demographics", output={"ok": True})],
    )

    sent = provider._client.models.last_contents  # type: ignore[attr-defined]
    assert len(sent) == 2
    for content in sent:
        assert content.role.upper() in LEGAL_ROLES, f"不合法的 role={content.role!r}"
