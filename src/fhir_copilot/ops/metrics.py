"""Prometheus 指標與 ``/metrics`` 端點。

**路徑標籤一定要用 route template,不能用原始路徑。** 兩個理由,第二個更重要:

1. cardinality:``/api/patients/<每一個病患 id>/summary`` 會產生無上限的
   time series,把 Prometheus 撐爆
2. **PII**:原始路徑裡就有 ``patient_id``。metrics 會被 scrape、儲存、
   在儀表板上顯示——那是病患識別碼最不該去的地方之一

所以標籤一律是 ``/api/patients/{patient_id}/summary`` 這種樣板字串。

``/metrics`` **預設不認證**:監控系統每 15 秒 scrape 一次,套用 API key 認證與
限流會直接把 scrape 打壞(不只要帶金鑰,還會被限流當成異常流量擋掉)。
但完全開放又會讓任何人看到當日花費與流量,所以留一個可選的
``FHIR_COPILOT_METRICS_TOKEN``——沒設就開放(demo 預設),有設才驗。
"""

from __future__ import annotations

import hmac
import os

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

METRICS_TOKEN_ENV = "FHIR_COPILOT_METRICS_TOKEN"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """一組指標 + 自己的 registry。

    用獨立 registry 而不是全域預設的:測試會反覆建立 app,共用全域 registry
    會在第二次註冊同名指標時炸掉。
    """

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "fhir_copilot_http_requests_total",
            "HTTP 請求數",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "fhir_copilot_http_request_duration_seconds",
            "HTTP 請求耗時",
            ["method", "route"],
            registry=self.registry,
        )
        self.provider_errors = Counter(
            "fhir_copilot_provider_errors_total",
            "provider 呼叫失敗次數",
            ["provider"],
            registry=self.registry,
        )
        self.refusals = Counter(
            "fhir_copilot_refusals_total",
            "結構化拒答次數(依原因)",
            ["reason"],
            registry=self.registry,
        )
        self.rejections = Counter(
            "fhir_copilot_ops_rejections_total",
            "營運層擋下的請求數(認證/限流/預算)",
            ["error_code"],
            registry=self.registry,
        )
        self.budget_spent = Gauge(
            "fhir_copilot_budget_spent_usd_today",
            "當日累計成本(美元);記憶體計數,重啟歸零",
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


def metrics_token() -> str | None:
    token = os.environ.get(METRICS_TOKEN_ENV, "").strip()
    return token or None


def token_is_valid(authorization_header: str | None) -> bool:
    """沒設定 token 時一律放行;設了就要求 ``Authorization: Bearer <token>``。"""
    expected = metrics_token()
    if expected is None:
        return True
    if not authorization_header:
        return False
    scheme, _, presented = authorization_header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(presented.strip(), expected)
