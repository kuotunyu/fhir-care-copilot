"""熔斷器狀態機。

**它在解決什麼**:provider 掛掉時,每個進來的請求都會等滿單次逾時(12 秒)才失敗。
7 個端點全是同步 ``def``、跑在 40 個 threadpool slot 上——只要每秒有 4 個請求,
不到 10 秒整個 threadpool 就被卡死的請求佔滿,連 ``/api/health`` 都排不進去。
熔斷的目的是**壞掉的時候快速失敗**,不是省錢。

狀態機:

    closed ──連續失敗達 failure_threshold──▶ open
      ▲                                        │
      │                                   recovery_seconds
      │                                        ▼
      └──連續成功達 half_open_successes── half_open
                                               │
                                          任一次失敗
                                               ▼
                                             open

半開狀態只放**一個**請求去探路(``try_acquire`` 用同一把鎖保證),否則 provider
還沒好就會被一整批重試請求再打垮一次。

執行緒安全用 ``threading.Lock``:handler 跑在 threadpool 的多個 worker thread 上,
不是 event loop(與限流、預算同一個理由)。
"""

from __future__ import annotations

import threading
import time
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """熔斷開啟中,請求沒有被送出去。"""

    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("熔斷開啟中,暫時不對 provider 發出請求")
        self.retry_after_seconds = retry_after_seconds


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
        half_open_successes: int,
    ) -> None:
        if failure_threshold <= 0 or half_open_successes <= 0:
            raise ValueError("failure_threshold 與 half_open_successes 都必須為正數")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.half_open_successes = half_open_successes

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_successes = 0
        self._opened_at = 0.0
        self._probe_in_flight = False

    def _now(self) -> float:
        return time.monotonic()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def try_acquire(self) -> CircuitState:
        """要求放行一次呼叫;不放行就 raise ``CircuitOpenError``。

        回傳的是**這次呼叫是在哪個狀態下發出的**,呼叫端要把它原封不動傳回
        ``record_success`` / ``record_failure``——不能在事後重讀 ``self._state``,
        因為那時候狀態可能已經被別的執行緒改掉了。
        """
        with self._lock:
            if self._state is CircuitState.OPEN:
                elapsed = self._now() - self._opened_at
                if elapsed < self.recovery_seconds:
                    raise CircuitOpenError(self.recovery_seconds - elapsed)
                # 冷卻夠久了,轉半開並讓這個請求去探路
                self._state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                self._probe_in_flight = True
                return CircuitState.HALF_OPEN

            if self._state is CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    # 半開時只放一個請求出去。provider 還沒好就被一整批重試
                    # 再打垮一次,是熔斷器最常見的實作錯誤。
                    raise CircuitOpenError(self.recovery_seconds)
                self._probe_in_flight = True
                return CircuitState.HALF_OPEN

            return CircuitState.CLOSED

    def record_success(self, acquired_state: CircuitState) -> CircuitState | None:
        """回傳發生變化後的新狀態;沒有變化回 ``None``。"""
        with self._lock:
            if acquired_state is CircuitState.HALF_OPEN:
                self._probe_in_flight = False
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_successes:
                    self._state = CircuitState.CLOSED
                    self._consecutive_failures = 0
                    self._half_open_successes = 0
                    return CircuitState.CLOSED
                return None
            self._consecutive_failures = 0
            return None

    def record_failure(self, acquired_state: CircuitState) -> CircuitState | None:
        with self._lock:
            if acquired_state is CircuitState.HALF_OPEN:
                # 探路失敗:立刻回到 open,重新計時
                self._probe_in_flight = False
                self._state = CircuitState.OPEN
                self._opened_at = self._now()
                self._half_open_successes = 0
                return CircuitState.OPEN

            self._consecutive_failures += 1
            if (
                self._state is CircuitState.CLOSED
                and self._consecutive_failures >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self._now()
                return CircuitState.OPEN
            return None

    def reset(self) -> None:
        """測試用,以及 ``reset_caches`` 之後的乾淨起點。"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._half_open_successes = 0
            self._opened_at = 0.0
            self._probe_in_flight = False
