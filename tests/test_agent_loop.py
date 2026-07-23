"""Agent loop 整合測試:guardrails、evidence、拒答、回應契約(PLAN.md M3)。"""

from collections.abc import Sequence
from typing import Any

import pytest

from fhir_copilot.agent.loop import _dedupe_evidence, answer_question
from fhir_copilot.config import Guardrails, load_pricing
from fhir_copilot.providers.base import ProviderStep, RequestedToolCall, ToolCallOutcome
from fhir_copilot.providers.mock import MockProvider
from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.tools.base import Evidence
from tests.conftest import AMY_ID, BEN_ID


@pytest.fixture
def guardrails() -> Guardrails:
    return Guardrails(
        max_tool_rounds=6, timeout_seconds=30, max_input_chars=4000, max_output_tokens=1024
    )


@pytest.fixture
def pricing() -> dict[str, Any]:
    return load_pricing()


class _LoopingProvider:
    """測試用 stub:永遠要求再呼叫一次工具,不給 final_answer——用來測 max_tool_rounds。"""

    model_id = "mock-deterministic"

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        return self._loop_step()

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        del state, outcomes
        return self._loop_step()

    @staticmethod
    def _loop_step() -> ProviderStep:
        call = RequestedToolCall(call_id="c", tool_name="get_patient_demographics", arguments={})
        return ProviderStep(
            state=None, tool_calls=(call,), final_answer=None, input_tokens=0, output_tokens=0
        )


def test_answers_with_evidence_and_zero_cost_via_mock(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=AMY_ID,
        question="他目前有在吃什麼藥?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert "Metformin" in result.answer
    assert len(result.evidence) >= 1
    assert all(e.resource_type == "MedicationRequest" for e in result.evidence)
    assert result.model == "mock-deterministic"
    assert result.estimated_cost_usd == 0.0
    assert result.latency_ms >= 0


def test_valid_empty_result_is_not_a_refusal(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    """Ben 存在但沒有照護計畫——這是合法的空結果,不該觸發拒答(M2 的設計語意)。"""
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=BEN_ID,
        question="他的照護計畫是什麼?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert "沒有照護計畫" in result.answer


def test_unknown_patient_is_structured_refusal(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id="no-such-patient",
        question="他的基本資料是什麼?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert result.evidence == []
    assert result.limitations is not None


def test_llm_cannot_smuggle_a_different_patient_id_via_tool_arguments(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    """ADR 0003:即使工具參數帶了別的 patient_id,loop 也一律用注入的那個。"""

    class _InjectingProvider:
        model_id = "mock-deterministic"

        def start(
            self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
        ) -> ProviderStep:
            del system_prompt, user_message, tool_specs
            call = RequestedToolCall(
                call_id="c",
                tool_name="get_patient_demographics",
                arguments={"patient_id": "some-other-patient-the-llm-made-up"},
            )
            return ProviderStep(
                state=None, tool_calls=(call,), final_answer=None, input_tokens=0, output_tokens=0
            )

        def continue_with_tool_results(
            self, state: Any, outcomes: Sequence[ToolCallOutcome]
        ) -> ProviderStep:
            del state
            return ProviderStep(
                state=None,
                tool_calls=(),
                final_answer=outcomes[0].output["demographics"]["name"],
                input_tokens=0,
                output_tokens=0,
            )

    result = answer_question(
        provider=_InjectingProvider(),
        store=store,
        patient_id=AMY_ID,
        question="姓名?",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is False
    assert result.answer == "Amy002 Fixture001"


def test_input_too_long_is_refused_before_any_tool_call(
    store: LocalBundleFHIRStore, pricing: dict[str, Any]
) -> None:
    guardrails = Guardrails(
        max_tool_rounds=6, timeout_seconds=30, max_input_chars=10, max_output_tokens=1024
    )

    result = answer_question(
        provider=MockProvider(),
        store=store,
        patient_id=AMY_ID,
        question="這個問題超過十個字元長度上限了喔",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_max_tool_rounds_guardrail_stops_infinite_loop(
    store: LocalBundleFHIRStore, pricing: dict[str, Any]
) -> None:
    guardrails = Guardrails(
        max_tool_rounds=1, timeout_seconds=30, max_input_chars=4000, max_output_tokens=1024
    )

    result = answer_question(
        provider=_LoopingProvider(),
        store=store,
        patient_id=AMY_ID,
        question="問題",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert "輪數" in (result.limitations or "")


def test_timeout_guardrail_trips(store: LocalBundleFHIRStore, pricing: dict[str, Any]) -> None:
    guardrails = Guardrails(
        max_tool_rounds=100, timeout_seconds=0, max_input_chars=4000, max_output_tokens=1024
    )

    result = answer_question(
        provider=_LoopingProvider(),
        store=store,
        patient_id=AMY_ID,
        question="問題",
        guardrails=guardrails,
        pricing=pricing,
    )

    assert result.refused is True
    assert "時間" in (result.limitations or "")


def test_dedupe_evidence_removes_exact_duplicates_preserving_order() -> None:
    e1 = Evidence(
        resource_type="Condition", resource_id="1", field="clinicalStatus", value="active"
    )
    e2 = Evidence(
        resource_type="Condition", resource_id="2", field="clinicalStatus", value="active"
    )
    deduped = _dedupe_evidence([e1, e2, e1])

    assert deduped == [e1, e2]
