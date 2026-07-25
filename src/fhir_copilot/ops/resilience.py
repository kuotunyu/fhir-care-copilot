"""``ResilientProvider``:單次呼叫的重試與熔斷。

包在 ``InstrumentedProvider`` 外面,同樣利用 ``Provider`` 是結構化型別這件事——
``agent/loop.py`` 不需要知道它存在。

**只重試「可能是暫時性」的失敗**。把所有例外都重試會做兩件壞事:把「輸入有問題」
這種必然再失敗的錯誤重打三次(白花錢),以及把程式 bug 藏在重試後面看不見。

**逾時不在這裡實作。** 單次呼叫的逾時下在 SDK 的 HTTP client(見
``providers/gemini.py`` 與 ``providers/openai_provider.py``),那才是真的中止請求。
在這一層用執行緒包 timeout 只能「不等它」,底層連線還在跑、執行緒也殺不掉,
等於把逾時變成 threadpool 洩漏——而 threadpool 飽和正是 Phase 0 量到的瓶頸。

**成本**:失敗的嘗試在 provider 端可能已經產生 token(例如生成到一半才逾時),
我們觀測不到。所以每次重試都透過 ``on_retry`` 回呼向預算計數補記一筆估算值,
**寧可高估也不要讓一次請求偷偷花三倍錢**。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from fhir_copilot.ops.circuit import CircuitBreaker, CircuitOpenError, CircuitState
from fhir_copilot.ops.config import ResilienceConfig
from fhir_copilot.ops.tracing import get_tracer
from fhir_copilot.providers.base import Provider, ProviderStep, ToolCallOutcome
from fhir_copilot.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


class ProviderUnavailableError(RuntimeError):
    """provider 重試後仍失敗,或熔斷開啟中。

    agent loop 會把它轉成結構化拒答——**不是 500**。provider 暫時壞掉是
    「已知的、預期內的」狀況,不是伺服器出錯。
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def is_retryable(exc: BaseException) -> bool:
    """這個例外值不值得重試。

    刻意用「例外類別名稱 + 訊息關鍵字」而不是 import 各家 SDK 的例外型別:
    provider adapter 是可插拔的,這一層不應該為了判斷錯誤而依賴特定 SDK。
    代價是判斷比較粗;誤判的後果是多打一次或少打一次,兩者都不嚴重。
    """
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    name = type(exc).__name__.lower()
    if any(token in name for token in ("timeout", "connection", "unavailable", "ratelimit")):
        return True
    text = str(exc).lower()
    return any(
        token in text
        for token in ("timeout", "timed out", "temporarily", "rate limit", "429", "503", "502")
    )


class ResilientProvider:
    def __init__(
        self,
        inner: Provider,
        config: ResilienceConfig,
        breaker: CircuitBreaker,
        *,
        on_retry: Callable[[], None] | None = None,
        on_state_change: Callable[[CircuitState], None] | None = None,
    ) -> None:
        self._inner = inner
        self._config = config
        self._breaker = breaker
        self._on_retry = on_retry
        self._on_state_change = on_state_change
        self.model_id = inner.model_id

    def _sleep_for(self, attempt: int) -> float:
        delay = self._config.backoff_initial_seconds * (
            self._config.backoff_multiplier ** (attempt - 1)
        )
        return min(delay, self._config.backoff_max_seconds)

    def _note_state_change(self, new_state: CircuitState | None) -> None:
        if new_state is None:
            return
        # 熔斷狀態變化要在 trace 上看得到(Phase 2 建好的鏈路),
        # 否則事後只會看到一片拒答,查不出是什麼時候開始壞的
        span = get_tracer().start_span("circuit.state_change")
        span.set_attribute("circuit.state", new_state.value)
        span.end()
        logger.warning("熔斷狀態變更", extra={"circuit_state": new_state.value})
        if self._on_state_change is not None:
            self._on_state_change(new_state)

    def _call(self, label: str, operation: Callable[[], ProviderStep]) -> ProviderStep:
        try:
            acquired = self._breaker.try_acquire()
        except CircuitOpenError as exc:
            raise ProviderUnavailableError(
                "provider 暫時無法回應(熔斷開啟中)",
                retry_after_seconds=exc.retry_after_seconds,
            ) from exc

        attempts = self._config.max_retries + 1
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                step = operation()
            except Exception as exc:
                last_error = exc
                if not is_retryable(exc) or attempt == attempts:
                    self._note_state_change(self._breaker.record_failure(acquired))
                    raise ProviderUnavailableError(f"provider 呼叫失敗:{exc}") from exc
                # 重試可能在 provider 端已經產生 token,補記估算成本
                if self._on_retry is not None:
                    self._on_retry()
                delay = self._sleep_for(attempt)
                logger.warning(
                    "provider 呼叫失敗,準備重試",
                    extra={"call": label, "attempt": attempt, "retry_in_seconds": delay},
                )
                time.sleep(delay)
            else:
                self._note_state_change(self._breaker.record_success(acquired))
                return step

        # 迴圈一定會 return 或 raise;這行只是讓型別檢查看得懂
        raise ProviderUnavailableError(f"provider 呼叫失敗:{last_error}")

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
    ) -> ProviderStep:
        return self._call(
            "start",
            lambda: self._inner.start(
                system_prompt=system_prompt, user_message=user_message, tool_specs=tool_specs
            ),
        )

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        return self._call(
            "continue", lambda: self._inner.continue_with_tool_results(state, outcomes)
        )
