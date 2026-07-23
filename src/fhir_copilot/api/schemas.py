"""API 專屬的 request/response 型別(不重複定義工具已有的 schema)。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from fhir_copilot.care_notes import CareNoteDraft
from fhir_copilot.store.base import PatientSummary
from fhir_copilot.tools import (
    CarePlanSummary,
    ConditionSummary,
    MedicationSummary,
    ObservationSummary,
    PatientDemographics,
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    status: str
    provider: str
    model_id: str
    demo_mode: bool
    patient_count: int


class PatientListResponse(BaseModel):
    model_config = ConfigDict(strict=True)

    patients: list[PatientSummary]


class PatientSummaryResponse(BaseModel):
    """病患摘要頁(時間軸)用——直接呼叫 M2 工具組出來,不經過 LLM。"""

    model_config = ConfigDict(strict=True)

    demographics: PatientDemographics | None
    conditions: list[ConditionSummary]
    medications: list[MedicationSummary]
    observations: list[ObservationSummary]
    care_plans: list[CarePlanSummary]


class ChatRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str
    question: str


class ProposeCareNoteRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str
    note_text: str


class ConfirmCareNoteRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    draft: CareNoteDraft
