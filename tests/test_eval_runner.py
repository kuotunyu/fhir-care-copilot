"""run_eval() 單元測試:正常執行、跑前預算估算、執行中預算提前停止。"""

from collections.abc import Sequence
from typing import Any

import pytest

from fhir_copilot.config import Guardrails, load_pricing
from fhir_copilot.eval.cases import generate_cases
from fhir_copilot.eval.runner import BudgetExceededError, estimate_total_cost_usd, run_eval
from fhir_copilot.providers.base import ProviderStep
from fhir_copilot.providers.mock import MockProvider
from fhir_copilot.store import LocalBundleFHIRStore


@pytest.fixture
def guardrails() -> Guardrails:
    return Guardrails(
        max_tool_rounds=6, timeout_seconds=30, max_input_chars=4000, max_output_tokens=1024
    )


@pytest.fixture
def pricing() -> dict[str, Any]:
    return load_pricing()


class _FixedCostProvider:
    """測試用 stub:每題回報固定(較大的)token 用量,搭配真實計價模型,
    用來讓 run_eval 的「執行中預算提前停止」路徑可被觸發。"""

    def __init__(self, model_id: str, tokens_per_call: int) -> None:
        self.model_id = model_id
        self._tokens = tokens_per_call

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[Any]
    ) -> ProviderStep:
        del system_prompt, user_message, tool_specs
        return ProviderStep(
            state=None,
            tool_calls=(),
            final_answer="固定答案",
            input_tokens=self._tokens,
            output_tokens=self._tokens,
        )

    def continue_with_tool_results(self, state: Any, outcomes: Sequence[Any]) -> ProviderStep:
        raise AssertionError("不會被呼叫:start() 直接回傳 final_answer")


def test_run_eval_with_mock_provider_completes_all_cases(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    cases = generate_cases(store, per_category=2, unanswerable_count=2, injection_count=2)

    results = run_eval(
        cases=cases, provider=MockProvider(), store=store, guardrails=guardrails, pricing=pricing
    )

    assert len(results) == len(cases)
    assert all(r.response.estimated_cost_usd == 0.0 for r in results)


def test_estimate_total_cost_usd_scales_with_case_count(pricing: dict[str, Any]) -> None:
    one = estimate_total_cost_usd(1, "gpt-5.4-mini", pricing)
    ten = estimate_total_cost_usd(10, "gpt-5.4-mini", pricing)
    assert ten == pytest.approx(one * 10)
    assert one > 0


def test_run_eval_raises_before_spending_when_preflight_estimate_too_high(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    cases = generate_cases(store, per_category=5, unanswerable_count=5, injection_count=5)
    # gpt-5.4-mini 的預估單價很足夠讓一個很小的預算直接被跑前估算擋下
    provider = MockProvider(model_id="gpt-5.4-mini")

    with pytest.raises(BudgetExceededError):
        run_eval(
            cases=cases,
            provider=provider,
            store=store,
            guardrails=guardrails,
            pricing=pricing,
            budget_usd=0.0001,
        )


def test_run_eval_stops_early_when_running_cost_exceeds_budget(
    store: LocalBundleFHIRStore, guardrails: Guardrails, pricing: dict[str, Any]
) -> None:
    """跑前估算(用固定 2000in/300out 假設)過關,但實際單題花費較高,
    執行到一半就該提前停止,不跑完全部題目。"""
    cases = generate_cases(store, per_category=1, unanswerable_count=1, injection_count=0)
    assert len(cases) >= 3
    provider = _FixedCostProvider(model_id="gpt-5.4-mini", tokens_per_call=2000)

    results = run_eval(
        cases=cases,
        provider=provider,
        store=store,
        guardrails=guardrails,
        pricing=pricing,
        budget_usd=0.02,
    )

    assert 0 < len(results) < len(cases)
