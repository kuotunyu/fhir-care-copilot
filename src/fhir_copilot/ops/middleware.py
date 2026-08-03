"""單一 middleware:request id + HTTP root span + 指標。

三件事寫在一起是刻意的——它們都需要「請求開始/結束」這同一個切點,拆成三個
middleware 會讓每個請求多繞兩層 ASGI,而且 span 與日誌的 request id 必須是同一個。

**為什麼 route template 而非原始路徑**:見 ``metrics`` 模組的說明——
原始路徑裡有 ``patient_id``。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from opentelemetry.trace import SpanKind, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fhir_copilot.ops.logging import set_request_id
from fhir_copilot.ops.metrics import Metrics
from fhir_copilot.ops.tracing import get_tracer

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}", flags=re.ASCII)

logger = logging.getLogger(__name__)

_UNMATCHED_ROUTE = "unmatched"


def normalize_request_id(value: str | None) -> str:
    """只沿用有限 ASCII request id;其餘以 server UUID 取代。"""
    if value is not None and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid.uuid4().hex


def _route_template(request: Request) -> str:
    """回傳 route 樣板(``/api/patients/{patient_id}/summary``)。

    比對不到 route 時回固定字串,**不要退回原始路徑**——那正是會把 patient_id
    洩進指標標籤的路。
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else _UNMATCHED_ROUTE


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Callable[..., Awaitable[None]], metrics: Metrics) -> None:
        super().__init__(app)
        self._metrics = metrics

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 合法 id 可跨服務串鏈;任意文字不得被反射到 log/trace/header/audit。
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        set_request_id(request_id)

        method = request.method
        started = time.perf_counter()
        tracer = get_tracer()
        # span 名稱先用 method,route 要等 call_next 之後才比對得出來
        with tracer.start_as_current_span(method, kind=SpanKind.SERVER) as span:
            try:
                response = await call_next(request)
            except Exception:
                route = _route_template(request)
                span.update_name(f"{method} {route}")
                span.set_status(StatusCode.ERROR)
                self._metrics.requests.labels(method, route, "500").inc()
                logger.exception("請求處理失敗", extra={"route": route, "method": method})
                raise

            route = _route_template(request)
            elapsed = time.perf_counter() - started

            span.update_name(f"{method} {route}")
            # 只設 route 樣板與狀態碼——url.path 原始值含 patient_id,刻意不設
            span.set_attribute("http.request.method", method)
            span.set_attribute("http.route", route)
            span.set_attribute("http.response.status_code", response.status_code)
            span.set_attribute("request.id", request_id)
            if response.status_code >= 500:
                span.set_status(StatusCode.ERROR)

            self._metrics.requests.labels(method, route, str(response.status_code)).inc()
            self._metrics.request_duration.labels(method, route).observe(elapsed)

            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "http_request",
                extra={
                    "method": method,
                    "route": route,
                    "status": response.status_code,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
            return response
