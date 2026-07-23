"""5 個唯讀工具共用的型別與輔助函式。

安全邊界(ADR 0001):所有工具皆唯讀;回傳值必附 ``evidence``(FHIR
resourceType/id),供回答附上可追溯來源、供 eval 驗證 citation validity。

「查無資料」語意(PLAN.md M2)區分兩種情況:
- ``ok=False``:工具**無法**回答(如病患 id 不存在)→ 結構化錯誤,不是空 list 混過去
- ``ok=True`` 但清單為空:病患確實存在,只是該類別剛好沒有資料(如無生效中用藥)
  ——這是可驗證的事實,不是「資料不足」,不該觸發拒答
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fhir_copilot.store.base import JsonDict


class ToolErrorCode(StrEnum):
    """工具查詢失敗的結構化理由。"""

    PATIENT_NOT_FOUND = "patient_not_found"


class Evidence(BaseModel):
    """指向單一 FHIR resource(欄位)的證據。"""

    model_config = ConfigDict(strict=True)

    resource_type: str
    resource_id: str
    field: str | None = None
    value: str | None = None


def patient_evidence(patient_id: str, field: str, value: str | None) -> Evidence:
    return Evidence(resource_type="Patient", resource_id=patient_id, field=field, value=value)


def resource_evidence(
    resource: JsonDict, field: str | None = None, value: str | None = None
) -> Evidence:
    return Evidence(
        resource_type=str(resource.get("resourceType", "")),
        resource_id=str(resource.get("id", "")),
        field=field,
        value=value,
    )
