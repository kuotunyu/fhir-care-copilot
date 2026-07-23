"""FastAPI 共用依賴:FHIRStore/provider/configs 的單例載入。

Provider 選擇邏輯(PLAN.md §7 HF Docker Space 設計):優先用
``FHIR_COPILOT_PROVIDER`` 環境變數;沒設就用 configs/models.yaml 的
``default_provider``;若選到的 provider 需要金鑰但環境變數沒設,自動退回
mock(demo mode)——不會因為忘記設金鑰就讓服務整個炸掉。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from fhir_copilot.config import (
    Guardrails,
    ModelPricing,
    load_guardrails,
    load_pricing,
    load_providers,
)
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
def get_provider() -> Provider:
    return make_provider(get_provider_name())


def reset_caches() -> None:
    """測試用:清掉 lru_cache,讓下次呼叫重新讀環境變數/檔案。"""
    get_store.cache_clear()
    get_pricing.cache_clear()
    get_guardrails.cache_clear()
    get_provider_name.cache_clear()
    get_provider.cache_clear()
