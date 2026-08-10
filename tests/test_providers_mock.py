"""MockProvider 單元測試(關鍵字選工具 + 結果渲染 + 負載測試用的可設定延遲)。"""

import time

import pytest

from fhir_copilot.providers.base import ToolCallOutcome
from fhir_copilot.providers.mock import MockProvider
from fhir_copilot.tools import READ_ONLY_TOOLS


def test_start_selects_tool_by_keyword_and_requests_one_call() -> None:
    provider = MockProvider()

    step = provider.start(
        system_prompt="sys", user_message="他目前有在吃什麼藥?", tool_specs=READ_ONLY_TOOLS
    )

    assert step.final_answer is None
    assert len(step.tool_calls) == 1
    assert step.tool_calls[0].tool_name == "list_active_medications"
    assert step.tool_calls[0].arguments == {}  # patient_id 由 agent loop 注入,mock 不該自己塞


def test_start_prioritizes_allergy_over_generic_medication_keyword() -> None:
    provider = MockProvider()

    step = provider.start(
        system_prompt="sys", user_message="他有藥物過敏嗎?", tool_specs=READ_ONLY_TOOLS
    )

    assert step.tool_calls[0].tool_name == "list_allergies"
    assert step.tool_calls[0].arguments == {}


def test_start_routes_unknown_question_to_structured_out_of_scope() -> None:
    provider = MockProvider()

    step = provider.start(
        system_prompt="sys", user_message="他的保險給付範圍是什麼?", tool_specs=READ_ONLY_TOOLS
    )

    assert step.tool_calls[0].tool_name == "report_out_of_scope"
    assert step.tool_calls[0].arguments == {
        "missing_information": "deterministic mock 未涵蓋此問題"
    }


def test_start_routes_clinical_advice_request_to_structured_out_of_scope() -> None:
    provider = MockProvider()

    step = provider.start(
        system_prompt="sys", user_message="請根據他的用藥建議治療劑量", tool_specs=READ_ONLY_TOOLS
    )

    assert step.tool_calls[0].tool_name == "report_out_of_scope"


def test_continue_with_tool_results_renders_final_answer_from_real_shape() -> None:
    provider = MockProvider()
    outcome = ToolCallOutcome(
        call_id="mock-call-1",
        tool_name="list_active_conditions",
        output={"ok": True, "conditions": [{"display": "Diabetes mellitus type 2 (disorder)"}]},
    )

    step = provider.continue_with_tool_results(None, [outcome])

    assert step.final_answer is not None
    assert "Diabetes" in step.final_answer
    assert step.tool_calls == ()


def test_continue_with_tool_results_handles_not_found() -> None:
    provider = MockProvider()
    outcome = ToolCallOutcome(
        call_id="mock-call-1",
        tool_name="get_patient_demographics",
        output={"ok": False, "error": "patient_not_found"},
    )

    step = provider.continue_with_tool_results(None, [outcome])

    assert step.final_answer is not None
    assert "查無" in step.final_answer


class TestConfigurableLatency:
    """負載測試需要 mock 能模擬真實 provider 的網路延遲。

    這個旋鈕預設關閉——不設就跟沒有這個功能時完全一樣,不會偷偷讓所有測試變慢。
    """

    def test_defaults_to_no_latency(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FHIR_COPILOT_MOCK_LATENCY_MS", raising=False)

        assert MockProvider().latency_ms == 0

    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHIR_COPILOT_MOCK_LATENCY_MS", "250")

        assert MockProvider().latency_ms == 250

    def test_explicit_argument_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHIR_COPILOT_MOCK_LATENCY_MS", "250")

        assert MockProvider(latency_ms=10).latency_ms == 10

    def test_unparseable_env_falls_back_to_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """量測用的旋鈕設錯值不該讓服務起不來——它不是安全邊界。"""
        monkeypatch.setenv("FHIR_COPILOT_MOCK_LATENCY_MS", "很久")

        assert MockProvider().latency_ms == 0

    def test_negative_latency_is_clamped_to_zero(self) -> None:
        assert MockProvider(latency_ms=-5).latency_ms == 0

    def test_both_provider_calls_sleep_so_one_turn_costs_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """一輪問答會呼叫 provider 兩次(start + continue),端到端延遲是兩倍。

        報表把這個換算寫進去,靠的就是這個行為。
        """
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep", slept.append)
        provider = MockProvider(latency_ms=300)

        provider.start(system_prompt="sys", user_message="哈囉", tool_specs=READ_ONLY_TOOLS)
        provider.continue_with_tool_results(None, [])

        assert slept == [0.3, 0.3]

    def test_no_sleep_call_at_all_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(time, "sleep", slept.append)
        provider = MockProvider(latency_ms=0)

        provider.start(system_prompt="sys", user_message="哈囉", tool_specs=READ_ONLY_TOOLS)
        provider.continue_with_tool_results(None, [])

        assert slept == []
