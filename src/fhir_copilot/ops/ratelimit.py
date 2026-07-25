"""每個呼叫者一個 token bucket 的限流。

**為什麼是 in-process 而不是 Redis**:這個服務是單一 uvicorn process
(Dockerfile 的 CMD 沒有 `--workers`),多加一個外部元件目前講不出領域理由。
代價誠實記在這裡:**多實例部署時每個實例各有一份計數**,限流會變成 N 倍。
真的要水平擴展時再換共用儲存,那時才有理由。

**為什麼是 ``threading.Lock`` 而不是 asyncio 原語**:7 個端點全部是同步 ``def``,
FastAPI 會把它們丟進 anyio threadpool 執行——計數器是被多個 worker thread 碰的,
不是被 event loop 碰的。
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """經典 token bucket:容量 ``burst``,以 ``requests_per_minute`` 的速率回填。"""

    def __init__(self, *, requests_per_minute: int, burst: int) -> None:
        if requests_per_minute <= 0 or burst <= 0:
            raise ValueError("requests_per_minute 與 burst 都必須為正數")
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self._refill_per_second = requests_per_minute / 60
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        # monotonic:不受系統時鐘調整影響
        return time.monotonic()

    def acquire(self, identity: str) -> int | None:
        """扣一個 token。

        成功回 ``None``;被擋下來回「還要等幾秒」(至少 1,``Retry-After`` 用)。
        """
        now = self._now()
        with self._lock:
            bucket = self._buckets.get(identity)
            if bucket is None:
                bucket = _Bucket(tokens=float(self.burst), updated_at=now)
                self._buckets[identity] = bucket

            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self.burst, bucket.tokens + elapsed * self._refill_per_second)
            bucket.updated_at = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return None

            missing = 1.0 - bucket.tokens
            return max(1, math.ceil(missing / self._refill_per_second))

    def reset(self) -> None:
        """測試用:清掉所有 bucket,讓每個測試從滿桶開始。"""
        with self._lock:
            self._buckets.clear()
