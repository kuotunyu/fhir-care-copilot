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
    """健康檢查。除了活著沒活著,也回報所有降級狀態——demo mode 是刻意的設計,
    不是要藏起來的缺陷,所以看的人要能一眼知道現在少了什麼保護。"""

    model_config = ConfigDict(strict=True)

    status: str
    provider: str
    model_id: str
    demo_mode: bool
    patient_count: int
    # ---- 營運層狀態(Phase 1)----
    auth_required: bool
    api_key_count: int  # 只回數量,永遠不回金鑰本身
    rate_limit_per_minute: int
    budget_limit_usd: float
    budget_spent_usd_today: float
    # ---- 稽核與預算的降級狀態(Phase 4)----
    audit_backend: str  # postgres | jsonl
    audit_available: bool  # false = 後端連不上,status 會是 degraded
    draft_signing_key_configured: bool  # false = 用 process 臨時金鑰,重啟後舊草稿失效
    budget_persistent: bool  # false = 記憶體計數,重啟歸零
    budget_counting_since: str  # 記憶體模式的起算時間——攤開講,不假裝它是持久的


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
