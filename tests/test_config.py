"""configs/ 載入的單元測試。"""

import pytest

from fhir_copilot.config import estimate_cost_usd, load_guardrails, load_pricing, load_providers


def test_load_pricing_has_mock_and_real_models() -> None:
    pricing = load_pricing()

    assert pricing["mock-deterministic"].input_per_1m_usd == 0.0
    assert pricing["gemini-2.5-flash-lite"].input_per_1m_usd == 0.10
    assert pricing["gemini-2.5-flash-lite"].output_per_1m_usd == 0.40
    assert pricing["gemini-3.1-flash-lite"].input_per_1m_usd == 0.25
    assert pricing["gemini-3.1-flash-lite"].output_per_1m_usd == 1.50
    # 目前實際在用的模型。缺單價時 estimate_cost_usd 會 raise,所以換模型
    # 一定要同步補這裡——這個斷言就是那道閘。
    assert pricing["gemini-3.5-flash-lite"].input_per_1m_usd == 0.30
    assert pricing["gemini-3.5-flash-lite"].output_per_1m_usd == 2.50
    assert pricing["gpt-5.4-mini"].input_per_1m_usd == 0.75
    assert pricing["gpt-5.4-mini"].output_per_1m_usd == 4.50


def test_load_providers_default_is_mock() -> None:
    providers, default = load_providers()

    assert default == "mock"
    assert providers["mock"].model_id == "mock-deterministic"
    assert providers["gemini"].model_id == "gemini-3.5-flash-lite"
    assert providers["gemini"].api_key_env == "GEMINI_API_KEY"
    assert providers["openai"].model_id == "gpt-5.4-mini"


def test_load_guardrails() -> None:
    guardrails = load_guardrails()

    assert guardrails.max_tool_rounds >= 1
    assert guardrails.timeout_seconds >= 1
    assert guardrails.max_input_chars >= 1


def test_estimate_cost_usd_mock_is_free() -> None:
    pricing = load_pricing()
    assert estimate_cost_usd("mock-deterministic", 10_000, 5_000, pricing) == 0.0


def test_estimate_cost_usd_computes_from_pricing() -> None:
    pricing = load_pricing()
    cost = estimate_cost_usd("gemini-2.5-flash-lite", 1_000_000, 1_000_000, pricing)
    assert cost == pytest.approx(0.10 + 0.40)


def test_estimate_cost_usd_unknown_model_raises() -> None:
    pricing = load_pricing()
    with pytest.raises(KeyError):
        estimate_cost_usd("no-such-model", 1, 1, pricing)
