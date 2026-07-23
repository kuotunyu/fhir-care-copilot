"""get_care_plan_timeline:病患照護計畫時間軸。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from fhir_copilot.fhir_utils import coding_text, datetime_sort_key
from fhir_copilot.store.base import FHIRStore, JsonDict, UnknownPatientError
from fhir_copilot.tools.base import Evidence, ToolErrorCode, resource_evidence


class GetCarePlanTimelineInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str


class CarePlanSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    display: str
    status: str | None
    period_start: str | None
    period_end: str | None
    activities: list[str]


class GetCarePlanTimelineResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    care_plans: list[CarePlanSummary] = []
    evidence: list[Evidence] = []


def _activity_labels(care_plan: JsonDict) -> list[str]:
    labels: list[str] = []
    for activity in care_plan.get("activity") or []:
        detail = activity.get("detail") or {}
        label = coding_text(detail.get("code"))
        if label:
            labels.append(label)
    return labels


def get_care_plan_timeline(
    store: FHIRStore, params: GetCarePlanTimelineInput
) -> GetCarePlanTimelineResult:
    try:
        store.get_patient(params.patient_id)
    except UnknownPatientError:
        return GetCarePlanTimelineResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    care_plans_raw = store.get_resources(params.patient_id, "CarePlan")
    # 用真正的 datetime 比較,不能直接比字串(見 fhir_utils.datetime_sort_key)
    care_plans_raw.sort(key=lambda cp: datetime_sort_key((cp.get("period") or {}).get("start")))

    care_plans: list[CarePlanSummary] = []
    evidence: list[Evidence] = []
    for care_plan in care_plans_raw:
        period = care_plan.get("period") or {}
        care_plans.append(
            CarePlanSummary(
                display=coding_text((care_plan.get("category") or [None])[0]) or "(未知照護計畫)",
                status=care_plan.get("status"),
                period_start=period.get("start"),
                period_end=period.get("end"),
                activities=_activity_labels(care_plan),
            )
        )
        evidence.append(resource_evidence(care_plan, "status", care_plan.get("status")))

    return GetCarePlanTimelineResult(ok=True, care_plans=care_plans, evidence=evidence)
