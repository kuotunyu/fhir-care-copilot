"""MockProvider 單元測試(關鍵字選工具 + 結果渲染)。"""

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


def test_start_falls_back_to_demographics_when_no_keyword_matches() -> None:
    provider = MockProvider()

    step = provider.start(system_prompt="sys", user_message="哈囉", tool_specs=READ_ONLY_TOOLS)

    assert step.tool_calls[0].tool_name == "get_patient_demographics"


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
