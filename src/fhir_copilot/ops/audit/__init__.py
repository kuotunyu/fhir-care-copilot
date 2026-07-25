"""可信任的稽核軌跡。

「這份稽核軌跡值得信任」是一個命題,需要**同時**回答三件事。只做其中兩件,
會得到兩個各自不完整的機制:

1. **進來時是真的嗎** —— ``POST /api/care-notes/confirm`` 原本完全不驗證 draft
   是不是這個系統產生的,client 可以自行捏造整份草稿(含 ``proposed_at``)直接
   寫進稽核 log。只做防竄改鏈的話,得到的是「一條防竄改的鏈,但鏈上第一環
   可能一開始就是假的」——見 ``signing``
2. **進去後沒被改嗎** —— 每一列帶前一列的雜湊,構成 hash chain。**這一層放在
   紀錄模型而不是資料庫**,所以檔案模式也有防竄改;否則「退回檔案模式」等於
   同時退掉防竄改,那個降級路徑就變成安全破口——見 ``chain``
3. **併發下不會遺失嗎** —— 原本是 ``open("a")`` 加兩次獨立 ``write``、無 flush、
   完全沒有鎖,而 handler 跑在 threadpool 的多個 worker thread 上——見 ``sinks``

認證(Phase 1)回答的是「是誰打進來的」,不是「這份草稿是不是這個系統產生的」,
所以第 1 點不是 Phase 1 能解決的。
"""

from fhir_copilot.ops.audit.chain import AuditRecord, ChainVerification, verify_chain
from fhir_copilot.ops.audit.sinks import AuditSink, JsonlAuditSink, resolve_audit_sink

__all__ = [
    "AuditRecord",
    "AuditSink",
    "ChainVerification",
    "JsonlAuditSink",
    "resolve_audit_sink",
    "verify_chain",
]
