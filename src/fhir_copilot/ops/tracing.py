"""OpenTelemetry tracing。

**為什麼不用 ``opentelemetry-instrumentation-fastapi``**:我們本來就要自己寫
middleware 來產生 request id,HTTP root span 順手在同一處建即可。
auto-instrumentation 會多帶五、六個套件並對框架做 monkeypatch——為了一個 span
不划算,也和這個專案「可審查、不堆技術」的調性相反。代價是 span 的命名與屬性
要自己對齊 OTel semantic conventions,已照 ``http.*`` / ``url.*`` 慣例命名。

**exporter 可選**(沿用「少一個環境變數也能跑」的哲學):

- 有 ``OTEL_EXPORTER_OTLP_ENDPOINT`` → 送 OTLP(``docker compose --profile dev up``
  起的 Jaeger 就是這個)
- 有 ``FHIR_COPILOT_TRACE_FILE`` → 每個 span 寫一行 JSON 到該檔案
  (產生 ``reports/traces/`` 樣本用的)
- 兩者皆無 → 仍然建立 span,但不匯出。**span 建立本身極廉價**,而預設把
  span 印到 stdout 會把結構化日誌淹掉

**PII**:span 屬性與日誌受同一套規則管(見 ``redaction``)。病患姓名、問題內容、
完整 ``patient_id`` 都不會出現在 span 上。
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
TRACE_FILE_ENV = "FHIR_COPILOT_TRACE_FILE"
SERVICE_NAME = "fhir-care-copilot"

TRACER_NAME = "fhir_copilot"

_provider: TracerProvider | None = None


class JsonFileSpanExporter(SpanExporter):
    """把 span 以每行一個 JSON 的形式附加到檔案。

    存在的理由是「可觀測性必須有消費端」:Jaeger 要 `docker compose` 起得來才看得到,
    而 commit 進 repo 的 trace 樣本不用跑任何東西就看得到。兩種都要。
    """

    def __init__(self, path: str) -> None:
        self._path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with open(self._path, "a", encoding="utf-8") as handle:
            for span in spans:
                handle.write(json.dumps(_span_to_dict(span), ensure_ascii=False) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        del timeout_millis
        return True


def _span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    context = span.get_span_context()
    parent = span.parent
    return {
        "name": span.name,
        "trace_id": format(context.trace_id, "032x") if context else None,
        "span_id": format(context.span_id, "016x") if context else None,
        "parent_span_id": format(parent.span_id, "016x") if parent else None,
        "start_time": span.start_time,
        "end_time": span.end_time,
        "duration_ms": (
            round((span.end_time - span.start_time) / 1_000_000, 3)
            if span.end_time and span.start_time
            else None
        ),
        "status": span.status.status_code.name,
        "attributes": dict(span.attributes or {}),
    }


def configure_tracing(force: bool = False) -> None:
    """建立 TracerProvider 並掛上 exporter。

    **這個模組自己持有 provider,不依賴 OTel 的全域單例。** 理由:OTel 的
    ``set_tracer_provider`` 只吃第一次呼叫,之後會被忽略——那會讓測試沒辦法
    換掉 exporter(例如 PII 斷言測試要把 span 導到暫存檔)。span 的父子關係走的是
    context API 而不是 provider,所以自己持有不影響巢狀結構。
    """
    global _provider
    if _provider is not None and not force:
        return

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))

    if os.environ.get(OTLP_ENDPOINT_ENV):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace_file = os.environ.get(TRACE_FILE_ENV)
    if trace_file:
        # Simple(非 Batch):產生樣本時要求「請求結束後檔案裡就有」,不要等批次送出
        provider.add_span_processor(SimpleSpanProcessor(JsonFileSpanExporter(trace_file)))

    _provider = provider


def get_tracer() -> trace.Tracer:
    if _provider is None:
        # 沒設定過就退回全域(通常是 NoOp)——不要因為忘了初始化就炸掉請求
        return trace.get_tracer(TRACER_NAME)
    return _provider.get_tracer(TRACER_NAME)


def flush() -> None:
    """把還沒送出的 span 逼出去(產生 trace 樣本、或測試要立刻讀檔時用)。"""
    if _provider is not None:
        _provider.force_flush()


def reset_for_tests() -> None:
    """測試用:丟掉現有 provider,讓下一次 ``configure_tracing`` 重讀環境變數。"""
    global _provider
    if _provider is not None:
        _provider.shutdown()
    _provider = None
