"""營運層的結構化拒絕。

刻意不 import FastAPI:這裡只描述「為什麼被擋下來」,怎麼變成 HTTP 回應是
``api/`` 的事。

**回應形狀為什麼長這樣**:前端唯一的 fetch 包裝(``app/src/api.ts`` 的
``request<T>()``)讀的是 ``body.detail`` 並當成字串顯示。所以 ``detail`` 必須
維持人類可讀的字串,結構化資訊放在同一層的其他欄位——用 ``detail`` 塞 dict
會讓前端顯示 ``[object Object]``。
"""

from __future__ import annotations

from typing import Any


class OpsRejection(Exception):
    """被營運層控制擋下來的請求(認證/限流/預算)。"""

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        error_code: str,
        retry_after_seconds: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
        self.extra = extra or {}

    def body(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"detail": self.detail, "error_code": self.error_code}
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        payload.update(self.extra)
        return payload

    def headers(self) -> dict[str, str]:
        if self.retry_after_seconds is None:
            return {}
        return {"Retry-After": str(self.retry_after_seconds)}


def missing_api_key(header_name: str) -> OpsRejection:
    return OpsRejection(
        status_code=401,
        detail=f"這個端點需要 API key。請在 {header_name} header 帶上金鑰。",
        error_code="missing_api_key",
    )


def invalid_api_key() -> OpsRejection:
    return OpsRejection(
        status_code=401,
        detail="API key 無效。",
        error_code="invalid_api_key",
    )


def rate_limited(retry_after_seconds: int, requests_per_minute: int) -> OpsRejection:
    return OpsRejection(
        status_code=429,
        detail=f"請求太頻繁(上限每分鐘 {requests_per_minute} 次),請稍後再試。",
        error_code="rate_limited",
        retry_after_seconds=retry_after_seconds,
        extra={"requests_per_minute": requests_per_minute},
    )


def budget_exceeded(
    *, spent_usd: float, limit_usd: float, seconds_until_reset: int
) -> OpsRejection:
    """回 429 而不是 500——這是「已知的、預期內的」拒絕,不是伺服器壞了。"""
    return OpsRejection(
        status_code=429,
        detail=(
            f"今日用量已達上限(已用 US${spent_usd:.4f} / 上限 US${limit_usd:.2f}),"
            "額度於每日 UTC 00:00 重置。"
        ),
        error_code="budget_exceeded",
        retry_after_seconds=seconds_until_reset,
        extra={"spent_usd": round(spent_usd, 6), "limit_usd": limit_usd},
    )
