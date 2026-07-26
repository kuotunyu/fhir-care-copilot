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


class TestQuotaFailover:
    """主金鑰的**每日配額**用完時換備援金鑰。

    2026-07-26 跑全量 eval 時真的撞到:免費層 500 req/day/model,主金鑰用完,
    整個 run 直接掛掉。``models.yaml`` 一直定義著 ``backup_api_key_envs``,
    但沒有任何程式讀它——**設定檔承諾的東西沒實作,比沒承諾更糟**。

    這和 ResilientProvider 的重試是兩件事:429 說「58 秒後再試」,而退避上限
    是 4 秒,重試幾次都一樣。**配額耗盡要換身分,不是等。**
    """

    @staticmethod
    def _patch_clients(monkeypatch: pytest.MonkeyPatch, exhausted: set[str]) -> list[str]:
        """攔下 genai.Client,讓「哪些金鑰配額用完」可以被腳本控制。

        換金鑰會**重建 client**,所以不能只把假 client 掛在 provider 上——
        那樣第二把金鑰會拿去打真的 API(第一版測試就是這樣才爆的)。
        """
        used: list[str] = []

        def fake_client(*, api_key: str, http_options: Any = None) -> Any:
            used.append(api_key)
            client = FakeClient()

            def generate_content(*, model: str, contents: Any, config: Any) -> Any:
                if api_key in exhausted:
                    raise RuntimeError(
                        "429 RESOURCE_EXHAUSTED. {'error': {'message': 'You exceeded "
                        "your current quota', 'status': 'RESOURCE_EXHAUSTED'}}"
                    )
                return _FakeResponse()

            client.models.generate_content = generate_content  # type: ignore[method-assign]
            return client

        monkeypatch.setattr("fhir_copilot.providers.gemini.genai.Client", fake_client)
        return used

    def test_switches_to_backup_when_quota_is_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        used = self._patch_clients(monkeypatch, exhausted={"primary"})
        provider = GeminiProvider(
            model_id="gemini-3.1-flash-lite", api_key="primary", backup_api_keys=["backup-1"]
        )

        step = provider.start(system_prompt="s", user_message="q", tool_specs=())

        assert step.final_answer == "假的最終回答"
        assert used == ["primary", "backup-1"], "配額用完必須換到備援金鑰"

    def test_skips_past_several_exhausted_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """實測發現配額是 per project——同一專案的幾把金鑰會一起用完,
        只有不同專案的那把救得了。所以要能連續換過好幾把。"""
        used = self._patch_clients(monkeypatch, exhausted={"primary", "b1", "b2"})
        provider = GeminiProvider(
            model_id="gemini-3.1-flash-lite",
            api_key="primary",
            backup_api_keys=["b1", "b2", "b3"],
        )

        provider.start(system_prompt="s", user_message="q", tool_specs=())

        assert used == ["primary", "b1", "b2", "b3"]

    def test_gives_up_when_every_key_is_exhausted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """對照組:全部用完就把例外丟出去,不要無限迴圈。"""
        self._patch_clients(monkeypatch, exhausted={"primary", "backup-1"})
        provider = GeminiProvider(
            model_id="gemini-3.1-flash-lite", api_key="primary", backup_api_keys=["backup-1"]
        )

        with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
            provider.start(system_prompt="s", user_message="q", tool_specs=())

    def test_non_quota_errors_do_not_burn_backup_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """對照組:400 是我們自己送錯,換金鑰沒有意義,不該浪費備援配額。"""
        used: list[str] = []

        def fake_client(*, api_key: str, http_options: Any = None) -> Any:
            used.append(api_key)
            client = FakeClient()

            def generate_content(*, model: str, contents: Any, config: Any) -> Any:
                raise RuntimeError("400 INVALID_ARGUMENT")

            client.models.generate_content = generate_content  # type: ignore[method-assign]
            return client

        monkeypatch.setattr("fhir_copilot.providers.gemini.genai.Client", fake_client)
        provider = GeminiProvider(
            model_id="gemini-3.1-flash-lite", api_key="primary", backup_api_keys=["backup-1"]
        )

        with pytest.raises(RuntimeError, match="400"):
            provider.start(system_prompt="s", user_message="q", tool_specs=())

        assert used == ["primary"], "非配額錯誤不該換金鑰"
