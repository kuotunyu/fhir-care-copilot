"""每日成本上限。

領域理由:``/api/chat`` 每次呼叫都花真錢,而端點目前完全開放。會被燒光的是
**同一個 API 帳號的額度**,所以這個計數是全域的,不是每個 key 各算各的
(那是限流在管的公平性問題,兩者刻意分開)。

沿用 ``eval/runner.py`` 已經在用的同一套語彙:跑前估算 → 超過就擋、不花錢 →
執行中累計實際花費。差別只在那邊是「整批 220 題」,這邊是「一次請求」。

**已知限制(必須誠實回報)**:計數在記憶體,重啟即歸零。``/api/health`` 會回報
``budget_counting_since``,讓看的人知道這個數字是從什麼時候開始算的。持久化留給
之後接資料庫時處理。
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta


class DailyBudget:
    """全 process 的當日累計成本(UTC 日界重置)。"""

    def __init__(self, *, daily_limit_usd: float) -> None:
        self.daily_limit_usd = daily_limit_usd
        self._lock = threading.Lock()
        self._day = self._today()
        self._spent_usd = 0.0
        # 誠實揭露用:這個計數是從什麼時候開始算的
        self.counting_since = datetime.now(UTC)

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    @staticmethod
    def seconds_until_utc_midnight() -> int:
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(1, int((tomorrow - now).total_seconds()))

    def _roll_over_if_needed(self) -> None:
        """呼叫端必須已經持有 lock。"""
        today = self._today()
        if today != self._day:
            self._day = today
            self._spent_usd = 0.0

    def spent_today_usd(self) -> float:
        with self._lock:
            self._roll_over_if_needed()
            return self._spent_usd

    def would_exceed(self, estimated_usd: float) -> bool:
        """這一發打下去會不會超過上限。"""
        with self._lock:
            self._roll_over_if_needed()
            return self._spent_usd + estimated_usd > self.daily_limit_usd

    def record(self, actual_usd: float) -> None:
        """記錄一次請求的實際花費(回應算出來的 ``estimated_cost_usd``)。"""
        with self._lock:
            self._roll_over_if_needed()
            self._spent_usd += actual_usd

    def reset(self) -> None:
        """測試用:歸零並重設起算時間。"""
        with self._lock:
            self._day = self._today()
            self._spent_usd = 0.0
            self.counting_since = datetime.now(UTC)
