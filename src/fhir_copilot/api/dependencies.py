"""FastAPI 共用依賴:FHIRStore/provider/configs 的單例載入,以及營運層守門。

Provider 選擇邏輯(PLAN.md §7 HF Docker Space 設計):優先用
``FHIR_COPILOT_PROVIDER`` 環境變數;沒設就用 configs/models.yaml 的
``default_provider``;若選到的 provider 需要金鑰但環境變數沒設,自動退回
mock(demo mode)——不會因為忘記設金鑰就讓服務整個炸掉。

營運層守門(PLAN.md §3.1 Phase 1)以 ``Depends`` 實作而非 middleware,理由:
只掛在會花錢/會寫入的端點上,``/api/health`` 就天然免疫——健康檢查不該因為
加了認證而壞掉,也不必去跟 ``StaticFiles`` 的 mount 順序打架。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from fhir_copilot.config import (
    Guardrails,
    ModelPricing,
    estimate_cost_usd,
    load_guardrails,
    load_pricing,
    load_providers,
)
from fhir_copilot.ops import errors
from fhir_copilot.ops.budget import DailyBudget
from fhir_copilot.ops.config import OpsConfig, load_ops
from fhir_copilot.ops.identity import (
    ANONYMOUS,
    anonymous_bucket_key,
    load_api_keys,
    require_auth,
    resolve_label,
)
from fhir_copilot.ops.instrumented_provider import InstrumentedProvider
from fhir_copilot.ops.metrics import Metrics
from fhir_copilot.ops.ratelimit import TokenBucketLimiter
from fhir_copilot.providers.base import Provider
from fhir_copilot.providers.factory import make_provider
from fhir_copilot.store import LocalBundleFHIRStore
from fhir_copilot.store.base import FHIRStore

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "processed" / "subset_100"
DEFAULT_AUDIT_LOG_PATH = REPO_ROOT / "audit_log" / "care_notes.jsonl"


def data_dir() -> Path:
    return Path(os.environ.get("FHIR_COPILOT_DATA_DIR", str(DEFAULT_DATA_DIR)))


def audit_log_path() -> Path:
    return Path(os.environ.get("FHIR_COPILOT_AUDIT_LOG_PATH", str(DEFAULT_AUDIT_LOG_PATH)))


@lru_cache
def get_store() -> FHIRStore:
    return LocalBundleFHIRStore(data_dir())


@lru_cache
def get_pricing() -> dict[str, ModelPricing]:
    return load_pricing()


@lru_cache
def get_guardrails() -> Guardrails:
    return load_guardrails()


def resolve_provider_name() -> str:
    providers, default = load_providers()
    requested = os.environ.get("FHIR_COPILOT_PROVIDER") or default
    if requested not in providers:
        logger.warning("未知的 provider '%s',退回 mock(demo mode)", requested)
        return "mock"
    config = providers[requested]
    if config.api_key_env and not os.environ.get(config.api_key_env):
        logger.warning(
            "provider '%s' 需要的金鑰環境變數 %s 未設定,退回 mock(demo mode)",
            requested,
            config.api_key_env,
        )
        return "mock"
    return requested


@lru_cache
def get_provider_name() -> str:
    return resolve_provider_name()


@lru_cache
def get_metrics() -> Metrics:
    return Metrics()


@lru_cache
def get_provider() -> Provider:
    """真正的 provider 外面包一層觀測。

    ``Provider`` 是 Protocol 且無狀態,所以 agent loop 分辨不出被包過——
    provider 呼叫的 span 與錯誤計數因此不需要改 ``agent/loop.py``。
    """
    name = get_provider_name()
    return InstrumentedProvider(make_provider(name), get_metrics(), name)


# ---- 營運層(Phase 1:認證、限流、預算上限) ----


def ops_config_path() -> Path | None:
    """``FHIR_COPILOT_OPS_CONFIG`` 可指向另一份 ops.yaml(測試與多環境用),
    沿用 ``FHIR_COPILOT_DATA_DIR`` 那組環境變數的慣例。"""
    override = os.environ.get("FHIR_COPILOT_OPS_CONFIG")
    return Path(override) if override else None


@lru_cache
def get_ops() -> OpsConfig:
    return load_ops(ops_config_path())


@lru_cache
def get_rate_limiter() -> TokenBucketLimiter:
    config = get_ops().rate_limit
    return TokenBucketLimiter(requests_per_minute=config.requests_per_minute, burst=config.burst)


@lru_cache
def get_budget() -> DailyBudget:
    return DailyBudget(daily_limit_usd=get_ops().budget.daily_limit_usd)


def guard_protected(request: Request) -> str:
    """認證 + 限流;回傳呼叫者 label(未啟用認證時是 ``anonymous``)。

    行為分三種,對應三種降級狀態(全部會在 ``/api/health`` 回報):

    1. **完全沒有設定金鑰** → 認證層等於關閉,一律當 ``anonymous`` 放行。
       這是 demo/HF Space 的預設狀態,服務不會因為少一個環境變數就不能用。
       但如果同時 ``FHIR_COPILOT_REQUIRE_AUTH=true``,那是設定矛盾——
       明確要求認證卻沒有任何金鑰可用,這時 fail closed(擋下來),不 fail open。
    2. **有設定金鑰,而請求帶了不對的金鑰** → 401。呼叫者顯然想認證,
       默默降級成匿名只會讓人搞不清楚狀況。
    3. **有設定金鑰,請求沒帶** → 要求認證時 401,否則放行為 ``anonymous``。

    **限流不管有沒有開認證都生效**——demo mode 一樣會花錢。帶金鑰時每把金鑰
    各自一個桶;匿名時**依來源 IP 分桶**,否則公開 demo 上所有訪客會共用同一個桶
    而互相餓死彼此(見 ``identity.anonymous_bucket_key``)。
    """
    ops = get_ops()
    keys = load_api_keys()
    presented = request.headers.get(ops.auth.header_name)

    if not keys:
        if require_auth():
            logger.error("設定矛盾:要求認證但未設定任何 API key,所有受保護端點都會被擋下")
            raise errors.missing_api_key(ops.auth.header_name)
        label = ANONYMOUS
    else:
        matched = resolve_label(presented, keys)
        if matched is None:
            if presented:
                raise errors.invalid_api_key()
            if require_auth():
                raise errors.missing_api_key(ops.auth.header_name)
            label = ANONYMOUS
        else:
            label = matched

    # 桶 key 與對外標籤刻意分開:桶 key 在匿名時含 IP(只在記憶體內當 key),
    # 回傳的 label 永遠不含 IP——IP 是個人資料,不該流進日誌與 metrics。
    bucket_key = label
    if label == ANONYMOUS:
        bucket_key = anonymous_bucket_key(
            request.client.host if request.client else None,
            request.headers.get("X-Forwarded-For"),
        )

    retry_after = get_rate_limiter().acquire(bucket_key)
    if retry_after is not None:
        raise errors.rate_limited(retry_after, ops.rate_limit.requests_per_minute)
    return label


def guard_costly(caller: Annotated[str, Depends(guard_protected)]) -> str:
    """在 ``guard_protected`` 之上再加每日預算的前置估算。

    只掛在真的會呼叫 LLM 的端點上(``/api/chat``);care-note 端點不花錢,
    只需要認證與限流。
    """
    ops = get_ops()
    # 缺單價時 estimate_cost_usd 會 raise,這裡**刻意不 catch**:
    # 成本算不出來比程式炸還危險(config.py 的既有哲學)。默默當 0 元會讓
    # 預算上限變成裝飾品。順帶一提,這讓它在「花錢之前」就炸,比原本
    # 在 agent loop 最後才炸更早。
    estimated = estimate_cost_usd(
        get_provider().model_id,
        ops.budget.estimated_input_tokens_per_request,
        ops.budget.estimated_output_tokens_per_request,
        get_pricing(),
    )
    budget = get_budget()
    if budget.would_exceed(estimated):
        raise errors.budget_exceeded(
            spent_usd=budget.spent_today_usd(),
            limit_usd=budget.daily_limit_usd,
            seconds_until_reset=DailyBudget.seconds_until_utc_midnight(),
        )
    return caller


def reset_caches() -> None:
    """測試用:清掉 lru_cache,讓下次呼叫重新讀環境變數/檔案。

    營運層的單例(限流 bucket、預算計數)也一併清掉——它們是 process 級狀態,
    不清的話測試會互相汙染(前一個測試把 bucket 用光,下一個就莫名 429)。
    """
    get_store.cache_clear()
    get_pricing.cache_clear()
    get_guardrails.cache_clear()
    get_provider_name.cache_clear()
    get_provider.cache_clear()
    get_ops.cache_clear()
    get_rate_limiter.cache_clear()
    get_budget.cache_clear()
    get_metrics.cache_clear()
