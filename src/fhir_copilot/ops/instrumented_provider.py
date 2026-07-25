"""把 Provider 包一層,替每次 provider 呼叫加 span 與錯誤計數。

**這是不改 ``agent/loop.py`` 就能觀測 provider 呼叫的關鍵。** ``Provider`` 是
``typing.Protocol``(結構化型別)而且無狀態——對話歷史透過顯式的 ``state`` 傳遞——
所以只要有同樣的 ``model_id`` 屬性與兩個方法,loop 就分辨不出被包過。
組裝的地方在 ``api/dependencies.get_provider()``,loop 一行都不用動。

**PII**:span 上只記 token 數與輸入**長度**,不記 ``user_message`` 內容,
也不記工具回傳值(那裡面有病患欄位)。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opentelemetry.trace import StatusCode

from fhir_copilot.ops.metrics import Metrics
from fhir_copilot.ops.tracing import get_tracer
from fhir_copilot.providers.base import Provider, ProviderStep, ToolCallOutcome
from fhir_copilot.tools.registry import ToolSpec


class InstrumentedProvider:
    """``Provider`` 的裝飾器;行為與被包的 provider 完全相同。"""

    def __init__(self, inner: Provider, metrics: Metrics, provider_name: str) -> None:
        self._inner = inner
        self._metrics = metrics
        self._provider_name = provider_name
        self.model_id = inner.model_id

    def _record_step(self, span: Any, step: ProviderStep) -> None:
        span.set_attribute("provider.input_tokens", step.input_tokens)
        span.set_attribute("provider.output_tokens", step.output_tokens)
        span.set_attribute("provider.tool_calls", len(step.tool_calls))
        span.set_attribute("provider.has_final_answer", step.final_answer is not None)

    def start(
        self, *, system_prompt: str, user_message: str, tool_specs: Sequence[ToolSpec]
    ) -> ProviderStep:
        with get_tracer().start_as_current_span("provider.start") as span:
            span.set_attribute("provider.name", self._provider_name)
            span.set_attribute("provider.model_id", self.model_id)
            # 只記長度,不記使用者問了什麼
            span.set_attribute("provider.input_chars", len(user_message))
            try:
                step = self._inner.start(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tool_specs=tool_specs,
                )
            except Exception:
                span.set_status(StatusCode.ERROR)
                self._metrics.provider_errors.labels(self._provider_name).inc()
                raise
            self._record_step(span, step)
            return step

    def continue_with_tool_results(
        self, state: Any, outcomes: Sequence[ToolCallOutcome]
    ) -> ProviderStep:
        with get_tracer().start_as_current_span("provider.continue") as span:
            span.set_attribute("provider.name", self._provider_name)
            span.set_attribute("provider.model_id", self.model_id)
            span.set_attribute("provider.tool_outcomes", len(outcomes))
            try:
                step = self._inner.continue_with_tool_results(state, outcomes)
            except Exception:
                span.set_status(StatusCode.ERROR)
                self._metrics.provider_errors.labels(self._provider_name).inc()
                raise
            self._record_step(span, step)
            return step
