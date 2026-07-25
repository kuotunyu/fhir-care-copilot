"""防竄改的 hash chain。

每一列都帶前一列的雜湊,所以改動任何一列都會讓它之後的所有列對不上——
**竄改者必須重算整條鏈才能不被發現**,而那需要能改寫整個儲存體。

**為什麼放在紀錄模型而不是資料庫**:如果鏈是靠 Postgres 的觸發器或約束實作的,
「無 ``DATABASE_URL`` 就退回檔案模式」這條降級路徑會同時退掉防竄改——
那個降級是刻意保留的產品特性(demo 要能跑),不該是安全破口。放在模型層則兩個
後端拿到完全一樣的保證。

**這個機制能證明什麼、不能證明什麼**(誠實記錄,ADR 0007 有完整說明):

- 能證明:**紀錄被改過或被刪過**。任何單列的改動都會在該列之後全部對不上
- 不能證明:**紀錄沒有被整段重寫**。有寫入權限的人可以重算整條鏈。要防這個
  需要把鏈尾定期送到這個系統改不到的地方(外部時間戳、另一個帳號的儲存體),
  那超出這個 Phase 的範圍
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

GENESIS_HASH = "0" * 64


class AuditRecord(BaseModel):
    """稽核軌跡的一列。

    ``ConfirmedCareNote`` 原本只有 4 個欄位,沒有 id、沒有 actor、沒有 request_id——
    也就是說事後看不出「這筆是誰、透過哪一次請求寫的」。稽核軌跡的價值一半在這裡。
    """

    model_config = ConfigDict(strict=True)

    sequence: int
    patient_id: str
    note_text: str
    proposed_at: str
    confirmed_at: str
    actor: str
    request_id: str
    prev_hash: str
    row_hash: str

    def payload(self) -> dict[str, Any]:
        """參與雜湊計算的欄位(``row_hash`` 自己不算在內)。"""
        return {
            "sequence": self.sequence,
            "patient_id": self.patient_id,
            "note_text": self.note_text,
            "proposed_at": self.proposed_at,
            "confirmed_at": self.confirmed_at,
            "actor": self.actor,
            "request_id": self.request_id,
            "prev_hash": self.prev_hash,
        }


def canonical_json(payload: dict[str, Any]) -> str:
    """雜湊前的正規化。

    ``sort_keys`` 與固定分隔符是必要的:同樣的內容序列化成不同字串就會得到不同
    雜湊,驗證會在資料其實沒被動過的情況下報錯。``ensure_ascii=False`` 讓中文
    以 UTF-8 參與計算,而不是 ``\\uXXXX`` 轉義後的形式——兩者雜湊不同,
    必須在寫入與驗證兩邊一致。
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_row_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_record(
    *,
    sequence: int,
    prev_hash: str,
    patient_id: str,
    note_text: str,
    proposed_at: str,
    confirmed_at: str,
    actor: str,
    request_id: str,
) -> AuditRecord:
    payload: dict[str, Any] = {
        "sequence": sequence,
        "patient_id": patient_id,
        "note_text": note_text,
        "proposed_at": proposed_at,
        "confirmed_at": confirmed_at,
        "actor": actor,
        "request_id": request_id,
        "prev_hash": prev_hash,
    }
    return AuditRecord.model_validate({**payload, "row_hash": compute_row_hash(payload)})


@dataclass
class ChainVerification:
    """驗證結果。壞掉時要能**指出是哪一列**,不能只說「有問題」。"""

    total: int = 0
    ok: bool = True
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return f"稽核鏈完整:{self.total} 列全部通過驗證"
        return f"稽核鏈有問題({self.total} 列中發現 {len(self.problems)} 處):\n" + "\n".join(
            f"  - {p}" for p in self.problems
        )


def verify_chain(records: list[AuditRecord]) -> ChainVerification:
    """逐列驗證。三種問題分開回報,因為它們代表不同的事:

    - ``row_hash`` 對不上 → **這一列的內容被改過**
    - ``prev_hash`` 接不起來 → **前面有列被刪掉、插入或重排**
    - ``sequence`` 不連續 → 同上,但更直接
    """
    result = ChainVerification(total=len(records))
    expected_prev = GENESIS_HASH

    for index, record in enumerate(records):
        recomputed = compute_row_hash(record.payload())
        if recomputed != record.row_hash:
            result.ok = False
            result.problems.append(
                f"第 {index + 1} 列(sequence={record.sequence}):內容被改過"
                f"(row_hash 應為 {recomputed[:12]}…,實際是 {record.row_hash[:12]}…)"
            )
        if record.prev_hash != expected_prev:
            result.ok = False
            result.problems.append(
                f"第 {index + 1} 列(sequence={record.sequence}):接不上前一列"
                f"(prev_hash 應為 {expected_prev[:12]}…,實際是 {record.prev_hash[:12]}…)"
                " —— 前面可能有列被刪除、插入或重新排序"
            )
        if record.sequence != index:
            result.ok = False
            result.problems.append(
                f"第 {index + 1} 列:sequence 應為 {index},實際是 {record.sequence}"
            )
        expected_prev = record.row_hash

    return result
