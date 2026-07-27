"""list_active_medications:目前生效中(status=active)的用藥清單。

Synthea 版本差異(已在 fixture 內兩種都覆蓋):
- 已結束的 status 有 ``stopped``(舊版,如 sep2019 樣本)與 ``completed``(v3.4.0+)
  兩種寫法;這裡只挑 ``status == "active"``,不受此差異影響。
- 藥品編碼可能是 ``medicationCodeableConcept``(直接內嵌)或 ``medicationReference``
  (參照 bundle 內的 Medication resource)——兩種都要處理。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_copilot.fhir_utils import coding_system_code, coding_text
from fhir_copilot.store.base import FHIRStore, JsonDict, UnknownPatientError
from fhir_copilot.tools.base import Evidence, ToolErrorCode, resource_evidence


class ListActiveMedicationsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str


class MedicationSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    display: str
    code_system: str | None
    code_value: str | None
    authored_on: str | None


class ListActiveMedicationsResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    medications: list[MedicationSummary] = []
    evidence: list[Evidence] = []


def _medication_concept(
    store: FHIRStore, patient_id: str, request: JsonDict
) -> tuple[JsonDict | None, JsonDict | None]:
    """回傳 (藥品 CodeableConcept, 解析出的 Medication resource)。

    第二個值只有在透過 ``medicationReference`` 解析時才非 None——呼叫端要另外
    幫這個 resource 補一筆 evidence,否則藥名事實只會被 MedicationRequest 的
    status evidence「附帶」證明,追溯不到真正含有藥名的來源(M2 審查發現)。
    """
    concept = request.get("medicationCodeableConcept")
    if concept is not None:
        return concept, None
    ref = (request.get("medicationReference") or {}).get("reference")
    if not ref:
        return None, None
    medication = store.resolve_reference(patient_id, ref)
    if medication is None:
        return None, None
    return medication.get("code"), medication


def list_active_medications(
    store: FHIRStore, params: ListActiveMedicationsInput
) -> ListActiveMedicationsResult:
    try:
        store.get_patient(params.patient_id)
    except UnknownPatientError:
        return ListActiveMedicationsResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    medications: list[MedicationSummary] = []
    evidence: list[Evidence] = []
    for request in store.get_resources(params.patient_id, "MedicationRequest"):
        if request.get("status") != "active":
            continue
        concept, resolved_medication = _medication_concept(store, params.patient_id, request)
        system, value = coding_system_code(concept)
        display = coding_text(concept) or "(未知藥品)"
        medications.append(
            MedicationSummary(
                display=display,
                code_system=system,
                code_value=value,
                authored_on=request.get("authoredOn"),
            )
        )
        evidence.append(resource_evidence(request, "status", "active"))
        if resolved_medication is not None:
            # 藥名/編碼實際來自這個 Medication resource,不是 MedicationRequest 本身
            evidence.append(resource_evidence(resolved_medication, "code", display))

    return ListActiveMedicationsResult(ok=True, medications=medications, evidence=evidence)
