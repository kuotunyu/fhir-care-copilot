"""FastAPI 路由(PLAN.md M4)。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from fhir_copilot.agent import AgentResponse, answer_question
from fhir_copilot.api.dependencies import (
    audit_log_path,
    get_budget,
    get_guardrails,
    get_ops,
    get_pricing,
    get_provider,
    get_provider_name,
    get_store,
    guard_costly,
    guard_protected,
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
from fhir_copilot.ops.identity import load_api_keys, require_auth
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

# 認證 + 限流。掛了它的端點就是「受保護端點」——這份清單的權威來源是程式,
# 不在設定檔重複列(理由同 guardrails.yaml 不重複列工具 allowlist)。
CallerDep = Annotated[str, Depends(guard_protected)]
# 認證 + 限流 + 每日預算前置估算。只給真的會呼叫 LLM 的端點。
CostlyCallerDep = Annotated[str, Depends(guard_costly)]


@router.get("/health")
def health(store: StoreDep, provider: ProviderDep) -> HealthResponse:
    """**永遠免認證**——健康檢查被認證擋住的話,它就不再是健康檢查了。

    同時誠實回報所有降級狀態(沿用 provider 退回 mock 時回報 demo_mode 的模式):
    現在有沒有開認證、限流門檻多少、今日花了多少、這個計數從什麼時候起算。
    """
    provider_name = get_provider_name()
    ops = get_ops()
    budget = get_budget()
    return HealthResponse(
        status="ok",
        provider=provider_name,
        model_id=provider.model_id,
        demo_mode=provider_name == "mock",
        patient_count=len(store.list_patients()),
        auth_required=require_auth(),
        api_key_count=len(load_api_keys()),
        rate_limit_per_minute=ops.rate_limit.requests_per_minute,
        budget_limit_usd=budget.daily_limit_usd,
        budget_spent_usd_today=round(budget.spent_today_usd(), 6),
        # 記憶體計數,重啟歸零——把起算時間攤開講,不假裝它是持久的
        budget_counting_since=budget.counting_since.isoformat(timespec="seconds"),
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
    caller: CostlyCallerDep,
) -> AgentResponse:
    """唯一會花錢的端點,所以是唯一同時受認證、限流與預算三層守門的端點。"""
    del caller  # 目前只用於守門與限流分桶;寫進日誌是 Phase 2 的事
    response = answer_question(
        provider=provider,
        store=store,
        patient_id=request.patient_id,
        question=request.question,
        guardrails=guardrails,
        pricing=pricing,
    )
    # 事後累計實際花費。依賴看不到回應,所以這一步只能在路由層做。
    # (拒答路徑也會走到這裡,而拒答的成本通常是 0——照記,不特別處理。)
    get_budget().record(response.estimated_cost_usd)
    return response


@router.post("/care-notes/propose")
def propose_note(
    request: ProposeCareNoteRequest, store: StoreDep, caller: CallerDep
) -> ProposeCareNoteResult:
    del caller
    result = propose_care_note(
        store, ProposeCareNoteInput(patient_id=request.patient_id, note_text=request.note_text)
    )
    if not result.ok:
        raise HTTPException(status_code=404, detail="查無此病患")
    return result


@router.post("/care-notes/confirm")
def confirm_note(request: ConfirmCareNoteRequest, caller: CallerDep) -> ConfirmedCareNote:
    del caller
    return confirm_and_log(request.draft, audit_log_path=audit_log_path())


@router.get("/providers")
def list_providers() -> dict[str, str]:
    """回報 configs/models.yaml 定義的 provider 名稱 -> model_id(前端顯示用)。"""
    providers, _default = load_providers()
    return {name: cfg.model_id for name, cfg in providers.items()}


__all__ = ["router"]
