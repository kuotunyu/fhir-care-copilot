"""``report_out_of_scope``:讓模型**明講**「這題六個資料工具都涵蓋不到」。

## 為什麼需要這個工具

在此之前,「病患存在但工具查不到」沒有任何結構性的處理。2026-07-26 實測
(gemini-3.1-flash-lite,問「他的保險給付範圍包含哪些項目?」)實際發生的是:

    模型呼叫了工具 → 拿到不相關的資料 → 回答「我無法查閱保險資訊」
    → 回應契約是 refused=False,而且掛著 3 筆與答案無關的 evidence

回答的內容是對的,契約卻是錯的。下游(eval 指標、UI、稽核)分辨不出
「查了資料而且答出來」與「查了資料但答不出來」,而那兩件事該做的下一步完全不同。

## 為什麼是工具,不是解析回答文字

判斷「模型是不是在拒答」如果靠關鍵字或語意判斷,就回到這個專案一直在避免的
東西:啟發式判準。eval 的 judge 在這件事上已經改過五次,還是不穩。

**給模型一個工具去宣告,把判斷問題變成結構問題。** 模型呼叫它 = 明確的訊號,
不需要任何猜測。這與整個專案的立場一致:事實與控制流程都走確定性的工具。

## 它為什麼還是唯讀

這個工具不碰資料庫、不回傳任何病患欄位、不產生 evidence——它只是把
「我答不出來」變成一個可偵測的事件。ADR 0001 的邊界沒有被放寬:
allowlist 仍然是 registry 那一份,裡面仍然沒有任何 write 類工具。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from fhir_copilot.store.base import FHIRStore
from fhir_copilot.tools.base import Evidence


class ReportOutOfScopeInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str
    # 讓模型說明它想查什麼。這個字串會進日誌(不進回應),用來看使用者實際上
    # 在問哪些現有工具涵蓋不到的東西——那是「下一個工具該做什麼」的證據。
    missing_information: str = Field(
        description="說明使用者想知道、但現有工具查不到的是什麼資訊",
        max_length=200,
    )


class ReportOutOfScopeResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool = True
    # loop 靠這個旗標認出「模型宣告了超出範圍」,不靠工具名稱字串比對
    out_of_scope: bool = True
    missing_information: str = ""
    evidence: list[Evidence] = []


def report_out_of_scope(store: FHIRStore, params: ReportOutOfScopeInput) -> ReportOutOfScopeResult:
    """不查任何東西,只把「查不到」這件事變成結構化訊號。"""
    del store  # 刻意不碰 store:這個工具不讀任何病患資料
    return ReportOutOfScopeResult(missing_information=params.missing_information)
