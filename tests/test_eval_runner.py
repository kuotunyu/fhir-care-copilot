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
from fhir_copilot.tools.registry import ToolSpec


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


def test_pace_seconds_sleeps_between_cases_but_not_before_the_first(
    store: LocalBundleFHIRStore,
    guardrails: Guardrails,
    pricing: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """打真實 API 時用來避免撞速率限制(實測 Gemini 免費層 15 req/min)——
    這裡只驗證 sleep 呼叫次數對不對,不真的等。"""
    sleeps: list[float] = []
    monkeypatch.setattr("fhir_copilot.eval.runner.time.sleep", lambda s: sleeps.append(s))

    cases = generate_cases(store, per_category=1, unanswerable_count=1, injection_count=0)
    assert len(cases) >= 2

    run_eval(
        cases=cases,
        provider=MockProvider(),
        store=store,
        guardrails=guardrails,
        pricing=pricing,
        pace_seconds=2.5,
    )

    assert sleeps == [2.5] * (len(cases) - 1)


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
    cases = generate_cases(
        store, per_category=1, unanswerable_count=1, injection_count=0, out_of_scope_count=0
    )
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


def test_unrecoverable_provider_error_keeps_completed_cases(
    store: LocalBundleFHIRStore, guardrails: Guardrails
) -> None:
    """跑到一半 provider 掛掉時,已完成的題目**不能丟掉**。

    2026-07-26 跑全量 eval 時主金鑰的每日配額用完(429 RESOURCE_EXHAUSTED),
    例外一路冒出去把整個 run 弄崩,幾十分鐘的真實 API 呼叫全部白花。
    處理方式比照既有的「預算超支就提前停」:停下來、保留結果、記清楚原因。
    """

    class DiesOnThirdCall(MockProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def start(
            self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
        ) -> ProviderStep:
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("429 RESOURCE_EXHAUSTED. quota exceeded")
            return super().start(
                system_prompt=system_prompt, user_message=user_message, tool_specs=tool_specs
            )

    cases = generate_cases(store, per_category=2, unanswerable_count=2, injection_count=2)[:5]
    results = run_eval(
        cases=cases,
        provider=DiesOnThirdCall(),
        store=store,
        guardrails=guardrails,
        pricing=load_pricing(),
        budget_usd=5.0,
    )

    assert 0 < len(results) < len(cases), "應該保留已完成的題目,而不是全丟或全跑完"
