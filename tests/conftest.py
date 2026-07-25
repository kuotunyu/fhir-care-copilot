"""共用 pytest fixtures。"""

from pathlib import Path

import pytest
import yaml

from fhir_copilot.store import LocalBundleFHIRStore

FIXTURES_DIR = Path(__file__).parent / "data" / "fixtures"

AMY_ID = "a1000000-0000-0000-0000-000000000001"
BEN_ID = "b2000000-0000-0000-0000-000000000001"

OPS_ENV_VARS = (
    "FHIR_COPILOT_API_KEYS",
    "FHIR_COPILOT_REQUIRE_AUTH",
    "FHIR_COPILOT_OPS_CONFIG",
)


@pytest.fixture(scope="session")
def store() -> LocalBundleFHIRStore:
    return LocalBundleFHIRStore(FIXTURES_DIR)


def clear_ops_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉營運層環境變數。

    開發機的 shell 或 .env 若剛好設了 API key,測試結果就會隨環境改變——
    測試必須自己決定自己的世界。
    """
    for name in OPS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_ops_config(
    path: Path,
    *,
    requests_per_minute: int = 600,
    burst: int = 600,
    daily_limit_usd: float = 1.0,
    max_retries: int = 2,
    failure_threshold: int = 5,
    recovery_seconds: float = 30.0,
    half_open_successes: int = 2,
) -> Path:
    """產生一份測試用 ops.yaml,回傳路徑。

    限流預設放得很寬,免得不是在測限流的測試被誤擋;要測限流的測試自己調低。
    退避時間刻意設成近乎 0:測試要驗的是「有沒有重試」,不是「真的睡了 0.5 秒」。
    """
    config = {
        "auth": {"header_name": "X-API-Key"},
        "rate_limit": {"requests_per_minute": requests_per_minute, "burst": burst},
        "budget": {
            "daily_limit_usd": daily_limit_usd,
            "estimated_input_tokens_per_request": 2000,
            "estimated_output_tokens_per_request": 300,
        },
        "resilience": {
            "provider_timeout_seconds": 12.0,
            "max_retries": max_retries,
            "backoff_initial_seconds": 0.001,
            "backoff_multiplier": 2.0,
            "backoff_max_seconds": 0.005,
            "failure_threshold": failure_threshold,
            "recovery_seconds": recovery_seconds,
            "half_open_successes": half_open_successes,
        },
        "load_test": {
            "mock_latency_ms": 0,
            "concurrency_ladder": [1],
            "duration_seconds": 1,
            "repeats": 1,
            "warmup_requests": 1,
            "targets": ["health"],
            "host": "127.0.0.1",
            "port": 8931,
        },
    }
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path
