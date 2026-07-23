"""HAPI FHIR server adapter — 預留介面,尚未實作(PLAN.md M1:只留 interface)。

之後接真正的 FHIR server 時,實作與 LocalBundleFHIRStore 相同的 FHIRStore
protocol(唯讀;write 方法依 ADR 0001 永不提供)。
"""

from __future__ import annotations

from fhir_copilot.store.base import JsonDict, PatientSummary


class HapiFHIRStore:
    """透過 HAPI FHIR base URL 讀取資料的 adapter(未實作)。"""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def list_patients(self) -> list[PatientSummary]:
        raise NotImplementedError("HAPI adapter 預留於後續 milestone 實作")

    def get_patient(self, patient_id: str) -> JsonDict:
        raise NotImplementedError("HAPI adapter 預留於後續 milestone 實作")

    def get_resources(self, patient_id: str, resource_type: str) -> list[JsonDict]:
        raise NotImplementedError("HAPI adapter 預留於後續 milestone 實作")

    def resolve_reference(self, patient_id: str, reference: str) -> JsonDict | None:
        raise NotImplementedError("HAPI adapter 預留於後續 milestone 實作")
