"""PII 遮蔽:決定什麼可以進日誌與 trace,什麼不行。

領域理由:日誌與 trace 會經手病患資料。**加了 tracing 卻讓病患姓名進 log,
比不加還糟**——原本資料只在記憶體裡待一次請求的時間,現在它會被寫進檔案、
送到 collector、留在別人的儲存空間裡。

這一層的原則是**白名單而非黑名單**:預設什麼都不記,只記明確判斷過安全的東西。
黑名單(「把姓名遮掉」)永遠會漏,因為你不可能列完所有會出現姓名的地方。

三條具體規則:

- ``patient_id`` → 雜湊後取前 8 碼。夠用來把同一個病患的多筆日誌串起來,
  但反推不回原值,也對不上 FHIR 資源
- 使用者輸入(``question``)與 ``note_text`` → **只記長度**,永不記內容。
  使用者可能在自由文字裡打進任何東西
- 病患姓名、性別、生日等 → **完全不記**。工具回傳值整包不進日誌,
  只記「呼叫了哪個工具、成功與否、拿到幾筆 evidence」

遮蔽最容易變成「有寫但沒效」,所以 ``tests/test_pii_redaction.py`` 會實際跑一次
完整請求、捕捉所有日誌與 span 輸出,斷言真實的病患姓名不在裡面。
"""

from __future__ import annotations

import hashlib

_HASH_PREFIX_LEN = 8


def hash_patient_id(patient_id: str) -> str:
    """把 ``patient_id`` 換成穩定但不可反推的短雜湊。

    同一個 id 一定得到同一個值(可以串起同一位病患的多筆日誌),
    但拿到雜湊反推不回 id,也查不到對應的 FHIR 資源。
    """
    if not patient_id:
        return "unknown"
    digest = hashlib.sha256(patient_id.encode("utf-8")).hexdigest()
    return digest[:_HASH_PREFIX_LEN]


def text_shape(text: str | None) -> dict[str, int]:
    """自由文字只留「形狀」,不留內容。

    長度足以看出「有沒有人在打超長輸入」「拒答的是不是空問題」這類營運問題,
    而這正是日誌需要回答的問題——它不需要知道使用者問了什麼。
    """
    return {"length": len(text or "")}


def safe_tool_summary(tool_name: str, output: dict[str, object]) -> dict[str, object]:
    """工具結果只留可稽核的骨架,不留任何病患欄位。

    ``evidence`` 的 ``resourceType``/``id`` 本身不是 PII(它們是 FHIR 資源識別碼,
    不含姓名或內容),但這裡仍只記**筆數**——要追哪一筆的話 trace 上有 span,
    日誌不需要重複一份。
    """
    evidence = output.get("evidence")
    return {
        "tool": tool_name,
        "ok": bool(output.get("ok", True)),
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
    }
