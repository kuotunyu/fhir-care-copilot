"""結構化 JSON 日誌 + request ID。

**這一層是從零建立的**:專案原本有 16 處 ``logger.*`` 呼叫,但沒有任何地方
呼叫 ``logging.basicConfig``,所以那些日誌實際上不會輸出。

用 stdlib ``logging`` + 自訂 formatter,不引 structlog——多一個依賴要能講出
理由,而這裡的需求(每行一個 JSON、帶 request id)stdlib 就做得到。

request id 用 ``contextvars`` 傳遞而不是參數:它要出現在**這個請求期間的每一行
日誌**,包括 store、tools、providers 這些完全不該知道 HTTP 存在的模組。
把它當參數一路傳下去會汙染所有函式簽名。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from typing import Any

LOG_LEVEL_ENV = "FHIR_COPILOT_LOG_LEVEL"
THIRD_PARTY_LEVEL_ENV = "FHIR_COPILOT_THIRD_PARTY_LOG_LEVEL"

# 這些函式庫會在 INFO 記下完整的請求 URL 與其他我們沒審查過的內容。
# 接管 root logger 等於也接管了它們的輸出,而**我們控制不了它們記什麼**——
# 對一個處理病患資料的服務,只該輸出內容由自己決定的日誌。
#
# 這不是假設性的顧慮:PII 斷言測試第一次跑就抓到 httpx 把含 patient_id 的
# URL 記進日誌(`GET /api/patients/<真實 id>/summary`)。降到 WARNING 之後,
# 真正的錯誤仍然看得到,例行的請求記錄則不再流出來。
_NOISY_THIRD_PARTY_LOGGERS = (
    "httpx",
    "httpx2",
    "httpcore",
    "urllib3",
    "openai",
    "google",
    "google_genai",
    "opentelemetry",
)

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

# LogRecord 的內建屬性;自訂欄位是「不在這份清單裡的」那些
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """每行一個 JSON 物件。

    ``ensure_ascii=False``:正體中文訊息要看得懂,不要變成一整片 \\uXXXX。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": get_request_id(),
            "message": record.getMessage(),
        }
        # logger.info("...", extra={"tool": "x"}) 的自訂欄位攤平到頂層
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | None = None) -> None:
    """設定 root logger。可重複呼叫(每個 ``create_app()`` 都會呼叫一次)。

    刻意接管 uvicorn 的 logger:否則 access log 會是純文字,同一個服務吐兩種
    格式的日誌,收集端要寫兩套解析。
    """
    resolved = (level or os.environ.get(LOG_LEVEL_ENV) or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(resolved)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    # 第三方函式庫預設只讓 WARNING 以上通過(理由見 _NOISY_THIRD_PARTY_LOGGERS)。
    # 除錯時可用 FHIR_COPILOT_THIRD_PARTY_LOG_LEVEL=DEBUG 打開,但那是**明確的
    # 決定**,不是預設就把不受控的內容寫出去。
    third_party = (os.environ.get(THIRD_PARTY_LEVEL_ENV) or "WARNING").upper()
    for name in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(third_party)
