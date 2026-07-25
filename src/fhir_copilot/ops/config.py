"""configs/ops.yaml 的載入與型別。

沿用 ``fhir_copilot.config`` 的慣例:pydantic ``strict=True`` 模型 +
``load_*(path: Path | None = None)`` 讓測試可以注入自己的設定檔。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "configs"


class AuthConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    header_name: str


class RateLimitConfig(BaseModel):
    """每個 key 一個 token bucket——公平性控制,與預算上限是兩件事。"""

    model_config = ConfigDict(strict=True)

    requests_per_minute: int
    burst: int


class BudgetConfig(BaseModel):
    """每日成本上限——帳號保護控制,全域累計而非每個 key 各算各的。"""

    model_config = ConfigDict(strict=True)

    daily_limit_usd: float
    estimated_input_tokens_per_request: int
    estimated_output_tokens_per_request: int


class LoadTestConfig(BaseModel):
    """負載測試參數(Phase 0 基線與 Phase 5 對照必須共用同一組值)。"""

    model_config = ConfigDict(strict=True)

    mock_latency_ms: int
    concurrency_ladder: list[int]
    duration_seconds: int
    repeats: int
    warmup_requests: int
    targets: list[str]
    host: str
    port: int


class OpsConfig(BaseModel):
    model_config = ConfigDict(strict=True)

    auth: AuthConfig
    rate_limit: RateLimitConfig
    budget: BudgetConfig
    load_test: LoadTestConfig


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_ops(path: Path | None = None) -> OpsConfig:
    return OpsConfig.model_validate(_read_yaml(path or CONFIGS_DIR / "ops.yaml"))
