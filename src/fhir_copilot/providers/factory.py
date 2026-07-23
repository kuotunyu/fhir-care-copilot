"""依 configs/models.yaml 建立 provider instance。"""

from __future__ import annotations

from fhir_copilot.config import load_providers
from fhir_copilot.providers.base import Provider
from fhir_copilot.providers.gemini import GeminiProvider
from fhir_copilot.providers.mock import MockProvider
from fhir_copilot.providers.openai_provider import OpenAIProvider


def make_provider(name: str | None = None) -> Provider:
    """建立 provider;``name`` 省略時用 configs/models.yaml 的 ``default_provider``。"""
    providers, default = load_providers()
    resolved = name or default
    if resolved not in providers:
        raise KeyError(f"models.yaml 沒有定義 provider '{resolved}'")
    model_id = providers[resolved].model_id
    if resolved == "mock":
        return MockProvider(model_id=model_id)
    if resolved == "gemini":
        return GeminiProvider(model_id=model_id)
    if resolved == "openai":
        return OpenAIProvider(model_id=model_id)
    raise KeyError(f"未知的 provider 名稱:'{resolved}'(models.yaml 有定義,但沒有對應實作)")
