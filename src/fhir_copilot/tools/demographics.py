"""get_patient_demographics:病患基本資料(姓名/性別/出生日期)。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_copilot.fhir_utils import patient_display_name
from fhir_copilot.store.base import FHIRStore, UnknownPatientError
from fhir_copilot.tools.base import Evidence, ToolErrorCode, patient_evidence


class GetPatientDemographicsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str


class PatientDemographics(BaseModel):
    model_config = ConfigDict(strict=True)

    patient_id: str
    name: str
    gender: str | None
    birth_date: str | None


class GetPatientDemographicsResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    demographics: PatientDemographics | None = None
    evidence: list[Evidence] = []


def get_patient_demographics(
    store: FHIRStore, params: GetPatientDemographicsInput
) -> GetPatientDemographicsResult:
    try:
        patient = store.get_patient(params.patient_id)
    except UnknownPatientError:
        return GetPatientDemographicsResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    name = patient_display_name(patient)
    gender = patient.get("gender")
    birth_date = patient.get("birthDate")

    evidence = [patient_evidence(params.patient_id, "name", name)]
    if gender:
        evidence.append(patient_evidence(params.patient_id, "gender", str(gender)))
    if birth_date:
        evidence.append(patient_evidence(params.patient_id, "birthDate", str(birth_date)))

    return GetPatientDemographicsResult(
        ok=True,
        demographics=PatientDemographics(
            patient_id=params.patient_id,
            name=name,
            gender=gender,
            birth_date=birth_date,
        ),
        evidence=evidence,
    )
