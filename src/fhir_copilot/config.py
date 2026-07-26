"""configs/ 底下 YAML 設定的載入與型別(PLAN.md §8:模型 id/單價/護欄不寫死在程式)。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent / "configs"


class ModelPricing(BaseModel):
    model_config = ConfigDict(strict=True)

    input_per_1m_usd: float
    output_per_1m_usd: float
    cached_input_per_1m_usd: float | None = None


class ProviderConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    model_id: str
    sdk: str | None = None
    api_key_env: str | None = None
    backup_api_key_envs: list[str] = []


class Guardrails(BaseModel):
    model_config = ConfigDict(strict=True)

    max_tool_rounds: int
    timeout_seconds: int
    max_input_chars: int
    max_output_tokens: int
    # 預設 True(安全的那一邊)。給預設值是為了讓既有直接建構 Guardrails 的測試
    # 不必全部改;configs/guardrails.yaml 仍然明確寫出來,不靠預設值。
    require_tool_call_before_answer: bool = True


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_pricing(path: Path | None = None) -> dict[str, ModelPricing]:
    data = _read_yaml(path or CONFIGS_DIR / "pricing.yaml")
    return {model_id: ModelPricing.model_validate(v) for model_id, v in data["models"].items()}


def load_providers(path: Path | None = None) -> tuple[dict[str, ProviderConfig], str]:
    data = _read_yaml(path or CONFIGS_DIR / "models.yaml")
    providers = {name: ProviderConfig.model_validate(v) for name, v in data["providers"].items()}
    return providers, str(data["default_provider"])


def load_guardrails(path: Path | None = None) -> Guardrails:
    data = _read_yaml(path or CONFIGS_DIR / "guardrails.yaml")
    return Guardrails.model_validate(data)


def estimate_cost_usd(
    model_id: str, input_tokens: int, output_tokens: int, pricing: dict[str, ModelPricing]
) -> float:
    """單價缺該模型 → 直接 raise,不要默默算成 0 元(成本不可信比程式炸還危險)。"""
    p = pricing.get(model_id)
    if p is None:
        raise KeyError(f"pricing.yaml 缺少模型 '{model_id}' 的單價設定")
    return (input_tokens / 1_000_000) * p.input_per_1m_usd + (
        output_tokens / 1_000_000
    ) * p.output_per_1m_usd
