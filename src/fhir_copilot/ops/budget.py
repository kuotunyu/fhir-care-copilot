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
from typing import Protocol, runtime_checkable


@runtime_checkable
class BudgetStore(Protocol):
    """持久化的計數後端(Phase 4 的 Postgres)。

    用 Protocol 而不是 ``isinstance(PostgresAuditSink)``:後者會強迫無條件
    import psycopg,那正好破壞「沒有 DATABASE_URL 也要能跑」這個硬性要求。
    """

    def budget_spent(self, day: str) -> float: ...

    def budget_add(self, day: str, amount: float) -> float: ...


class DailyBudget:
    """當日累計成本(UTC 日界重置)。

    有 ``store`` 時計數存在資料庫,**重啟不歸零**、多實例共用同一個額度;
    沒有時退回記憶體計數(``/api/health`` 會標明起算時間)。
    """

    def __init__(self, *, daily_limit_usd: float, store: BudgetStore | None = None) -> None:
        self.daily_limit_usd = daily_limit_usd
        self._store = store
        self._lock = threading.Lock()
        self._day = self._today()
        self._spent_usd = 0.0
        # 誠實揭露用:這個計數是從什麼時候開始算的(記憶體模式才有意義)
        self.counting_since = datetime.now(UTC)

    @property
    def is_persistent(self) -> bool:
        return self._store is not None

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
        if self._store is not None:
            return self._store.budget_spent(self._today())
        with self._lock:
            self._roll_over_if_needed()
            return self._spent_usd

    def would_exceed(self, estimated_usd: float) -> bool:
        """這一發打下去會不會超過上限。"""
        return self.spent_today_usd() + estimated_usd > self.daily_limit_usd

    def record(self, actual_usd: float) -> None:
        """記錄一次請求的實際花費(回應算出來的 ``estimated_cost_usd``)。"""
        if self._store is not None:
            # 原子累加,不是「先讀再寫」——後者在併發下會漏記
            self._store.budget_add(self._today(), actual_usd)
            return
        with self._lock:
            self._roll_over_if_needed()
            self._spent_usd += actual_usd

    def reset(self) -> None:
        """測試用:歸零並重設起算時間。"""
        with self._lock:
            self._day = self._today()
            self._spent_usd = 0.0
            self.counting_since = datetime.now(UTC)
