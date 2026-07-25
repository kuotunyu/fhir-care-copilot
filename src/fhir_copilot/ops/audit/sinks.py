"""稽核軌跡的兩個後端。

**必須可選**(PLAN.md §3.1 Phase 4):沒有 ``DATABASE_URL`` 就退回檔案模式,
服務照樣起得來,``/api/health`` 明確回報現在用哪一種。這是這個專案能當 demo、
能上 HF Space 的前提,與 provider 缺金鑰退回 mock 是同一個哲學。

兩個後端拿到**完全相同的防竄改保證**——hash chain 在紀錄模型層(``chain``),
不是資料庫層。降級不該同時降掉安全性。

差別在**併發保證**:

| | 多執行緒 | 多 process |
|---|---|---|
| JSONL | 安全(``threading.Lock`` + 單次原子寫入) | **不安全** |
| Postgres | 安全 | 安全(交易 + 列鎖) |

原本的實作連多執行緒都不安全:``open("a")`` 加**兩次獨立的 ``write``**、
沒有 flush、沒有任何鎖,而 handler 跑在 threadpool 的多個 worker thread 上。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Protocol

from fhir_copilot.ops.audit.chain import GENESIS_HASH, AuditRecord, build_record

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"


class AuditSink(Protocol):
    """append-only。**刻意沒有 update 與 delete**——與 ``FHIRStore`` 沒有 write
    方法是同一個作法:做不到的事應該是「根本沒有這個方法」,不是「被擋下來」。"""

    backend: str

    def append(
        self,
        *,
        patient_id: str,
        note_text: str,
        proposed_at: str,
        confirmed_at: str,
        actor: str,
        request_id: str,
    ) -> AuditRecord: ...

    def read_all(self) -> list[AuditRecord]: ...


class JsonlAuditSink:
    """檔案模式。

    修掉原本的三個問題:單次原子寫入(不是兩次 write)、``flush`` + ``fsync``、
    以及 ``threading.Lock``。

    **誠實記錄的限制**:鎖是 process 內的,所以多 process(``uvicorn --workers N``、
    或多個容器共用一個 volume)仍然不安全。那正是 Postgres 模式存在的理由,
    不是拿檔案鎖硬撐——跨平台檔案鎖在 Windows 與 POSIX 的語意不同,
    而且仍然擋不住 NFS 之類的情況。
    """

    backend = "jsonl"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def read_all(self) -> list[AuditRecord]:
        if not self._path.is_file():
            return []
        records: list[AuditRecord] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(AuditRecord.model_validate_json(line))
        return records

    def append(
        self,
        *,
        patient_id: str,
        note_text: str,
        proposed_at: str,
        confirmed_at: str,
        actor: str,
        request_id: str,
    ) -> AuditRecord:
        with self._lock:
            existing = self.read_all()
            record = build_record(
                sequence=len(existing),
                prev_hash=existing[-1].row_hash if existing else GENESIS_HASH,
                patient_id=patient_id,
                note_text=note_text,
                proposed_at=proposed_at,
                confirmed_at=confirmed_at,
                actor=actor,
                request_id=request_id,
            )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 一次 write 寫完整行(含換行)。原本拆成兩次 write,在併發下會產生
            # 交錯與孤行——那不是理論風險,是這個檔案原本真實存在的競態。
            line = record.model_dump_json() + "\n"
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            return record


def database_url() -> str | None:
    return os.environ.get(DATABASE_URL_ENV, "").strip() or None


def resolve_audit_sink(jsonl_path: Path) -> AuditSink:
    """有 ``DATABASE_URL`` 就用 Postgres,否則退回 JSONL。

    **設定了 URL 但驅動沒裝時刻意讓它炸掉**,不默默退回檔案模式:
    那會讓人以為紀錄進了資料庫,其實在檔案裡——稽核軌跡的位置不能靠猜。
    """
    url = database_url()
    if url is None:
        return JsonlAuditSink(jsonl_path)

    try:
        from fhir_copilot.ops.audit.postgres import PostgresAuditSink
    except ImportError as exc:
        raise RuntimeError(
            "設定了 DATABASE_URL 但沒有安裝 postgres extra。"
            "請執行 `uv sync --extra postgres`,或取消設定 DATABASE_URL 以使用檔案模式。"
        ) from exc

    logger.info("稽核軌跡使用 Postgres 後端")
    return PostgresAuditSink(url)
