"""list_active_conditions:目前生效中(clinicalStatus=active)的診斷。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_copilot.fhir_utils import coding_system_code, coding_text
from fhir_copilot.store.base import FHIRStore, JsonDict, UnknownPatientError
from fhir_copilot.tools.base import Evidence, ToolErrorCode, resource_evidence


class ListActiveConditionsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str


class ConditionSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    display: str
    code_system: str | None
    code_value: str | None
    onset_date: str | None


class ListActiveConditionsResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    conditions: list[ConditionSummary] = []
    evidence: list[Evidence] = []


def _clinical_status(condition: JsonDict) -> str | None:
    coding = (condition.get("clinicalStatus") or {}).get("coding") or []
    if not coding:
        return None
    code = coding[0].get("code")
    return str(code) if code else None


def list_active_conditions(
    store: FHIRStore, params: ListActiveConditionsInput
) -> ListActiveConditionsResult:
    try:
        store.get_patient(params.patient_id)
    except UnknownPatientError:
        return ListActiveConditionsResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    conditions: list[ConditionSummary] = []
    evidence: list[Evidence] = []
    for condition in store.get_resources(params.patient_id, "Condition"):
        if _clinical_status(condition) != "active":
            continue
        code = condition.get("code")
        system, value = coding_system_code(code)
        conditions.append(
            ConditionSummary(
                display=coding_text(code) or "(未知診斷)",
                code_system=system,
                code_value=value,
                onset_date=condition.get("onsetDateTime"),
            )
        )
        evidence.append(resource_evidence(condition, "clinicalStatus", "active"))

    return ListActiveConditionsResult(ok=True, conditions=conditions, evidence=evidence)
