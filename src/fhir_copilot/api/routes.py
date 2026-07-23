"""FastAPI 路由(PLAN.md M4)。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from fhir_copilot.agent import AgentResponse, answer_question
from fhir_copilot.api.dependencies import (
    audit_log_path,
    get_guardrails,
    get_pricing,
    get_provider,
    get_provider_name,
    get_store,
)
from fhir_copilot.api.schemas import (
    ChatRequest,
    ConfirmCareNoteRequest,
    HealthResponse,
    PatientListResponse,
    PatientSummaryResponse,
    ProposeCareNoteRequest,
)
from fhir_copilot.care_notes import (
    ConfirmedCareNote,
    ProposeCareNoteInput,
    ProposeCareNoteResult,
    confirm_and_log,
    propose_care_note,
)
from fhir_copilot.config import Guardrails, ModelPricing, load_providers
from fhir_copilot.providers.base import Provider
from fhir_copilot.store.base import FHIRStore
from fhir_copilot.tools import (
    GetCarePlanTimelineInput,
    GetPatientDemographicsInput,
    GetRecentObservationsInput,
    ListActiveConditionsInput,
    ListActiveMedicationsInput,
    get_care_plan_timeline,
    get_patient_demographics,
    get_recent_observations,
    list_active_conditions,
    list_active_medications,
)

router = APIRouter(prefix="/api")

StoreDep = Annotated[FHIRStore, Depends(get_store)]
ProviderDep = Annotated[Provider, Depends(get_provider)]
GuardrailsDep = Annotated[Guardrails, Depends(get_guardrails)]
PricingDep = Annotated[dict[str, ModelPricing], Depends(get_pricing)]


@router.get("/health")
def health(store: StoreDep, provider: ProviderDep) -> HealthResponse:
    provider_name = get_provider_name()
    return HealthResponse(
        status="ok",
        provider=provider_name,
        model_id=provider.model_id,
        demo_mode=provider_name == "mock",
        patient_count=len(store.list_patients()),
    )


@router.get("/patients")
def list_patients(store: StoreDep) -> PatientListResponse:
    return PatientListResponse(patients=store.list_patients())


@router.get("/patients/{patient_id}/summary")
def patient_summary(patient_id: str, store: StoreDep) -> PatientSummaryResponse:
    """時間軸用:直接呼叫 M2 工具組出來,不經過 LLM。"""
    demographics = get_patient_demographics(
        store, GetPatientDemographicsInput(patient_id=patient_id)
    )
    if not demographics.ok:
        raise HTTPException(status_code=404, detail="查無此病患")

    conditions = list_active_conditions(store, ListActiveConditionsInput(patient_id=patient_id))
    medications = list_active_medications(store, ListActiveMedicationsInput(patient_id=patient_id))
    observations = get_recent_observations(
        store, GetRecentObservationsInput(patient_id=patient_id, limit=20)
    )
    care_plans = get_care_plan_timeline(store, GetCarePlanTimelineInput(patient_id=patient_id))

    return PatientSummaryResponse(
        demographics=demographics.demographics,
        conditions=conditions.conditions,
        medications=medications.medications,
        observations=observations.observations,
        care_plans=care_plans.care_plans,
    )


@router.post("/chat")
def chat(
    request: ChatRequest,
    store: StoreDep,
    provider: ProviderDep,
    guardrails: GuardrailsDep,
    pricing: PricingDep,
) -> AgentResponse:
    return answer_question(
        provider=provider,
        store=store,
        patient_id=request.patient_id,
        question=request.question,
        guardrails=guardrails,
        pricing=pricing,
    )


@router.post("/care-notes/propose")
def propose_note(request: ProposeCareNoteRequest, store: StoreDep) -> ProposeCareNoteResult:
    result = propose_care_note(
        store, ProposeCareNoteInput(patient_id=request.patient_id, note_text=request.note_text)
    )
    if not result.ok:
        raise HTTPException(status_code=404, detail="查無此病患")
    return result


@router.post("/care-notes/confirm")
def confirm_note(request: ConfirmCareNoteRequest) -> ConfirmedCareNote:
    return confirm_and_log(request.draft, audit_log_path=audit_log_path())


@router.get("/providers")
def list_providers() -> dict[str, str]:
    """回報 configs/models.yaml 定義的 provider 名稱 -> model_id(前端顯示用)。"""
    providers, _default = load_providers()
    return {name: cfg.model_id for name, cfg in providers.items()}


__all__ = ["router"]
