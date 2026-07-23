"""FHIRStore 介面與共用型別。

安全邊界(ADR 0001):此 Protocol 刻意只定義讀取方法。
write 類方法不是「被擋下」,而是「根本不存在」——任何實作都不得新增。
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

JsonDict = dict[str, Any]


class UnknownPatientError(KeyError):
    """查無此病患 id。呼叫端(工具層)應轉成結構化拒答,不得硬答。"""

    def __init__(self, patient_id: str) -> None:
        super().__init__(patient_id)
        self.patient_id = patient_id


class PatientSummary(BaseModel):
    """病患索引摘要(來源檔案保留,供追溯)。"""

    patient_id: str
    name: str
    gender: str | None = None
    birth_date: str | None = None
    source_file: str


class FHIRStore(Protocol):
    """唯讀 FHIR 資料存取介面。

    回傳的 resource 為原始 FHIR JSON(dict);呼叫端不得就地修改。
    """

    def list_patients(self) -> list[PatientSummary]:
        """列出全部病患摘要(穩定排序)。"""
        ...

    def get_patient(self, patient_id: str) -> JsonDict:
        """回傳該病患的 Patient resource。查無此人 raise UnknownPatientError。"""
        ...

    def get_resources(self, patient_id: str, resource_type: str) -> list[JsonDict]:
        """回傳該病患 bundle 內指定 resourceType 的全部 resources(可為空 list)。"""
        ...

    def resolve_reference(self, patient_id: str, reference: str) -> JsonDict | None:
        """解析 bundle 內參照(urn:uuid: 或 Type/id)。

        無法解析(含 conditional search URL,如 ``Practitioner?identifier=...``;
        或 ``#`` 開頭的 contained resource 參照)一律回傳 None,不 raise。
        """
        ...
