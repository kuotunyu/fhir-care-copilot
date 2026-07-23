"""make_provider() 工廠測試:確認 model_id 真的從 configs/models.yaml 讀入,
不是寫死在各 provider class 裡(修正 M3 review 發現的架構問題)。"""

import pytest

from fhir_copilot.providers.factory import make_provider
from fhir_copilot.providers.mock import MockProvider


def test_default_provider_is_mock_with_configured_model_id() -> None:
    provider = make_provider()
    assert isinstance(provider, MockProvider)
    assert provider.model_id == "mock-deterministic"


def test_named_mock_provider() -> None:
    provider = make_provider("mock")
    assert provider.model_id == "mock-deterministic"


def test_gemini_and_openai_require_api_key_but_model_id_comes_from_config() -> None:
    """不需要真的打 API——只驗證 model_id 在建構失敗前就已經是 configs/models.yaml
    設定的值(GeminiProvider/OpenAIProvider 建構子在缺 key 時會 raise,
    所以這裡改用能直接讀 configs 的 load_providers 驗證對應關係)。"""
    from fhir_copilot.config import load_providers

    providers, _default = load_providers()
    assert providers["gemini"].model_id == "gemini-3.1-flash-lite"
    assert providers["openai"].model_id == "gpt-5.4-mini"


def test_unknown_provider_name_raises() -> None:
    with pytest.raises(KeyError):
        make_provider("no-such-provider")
