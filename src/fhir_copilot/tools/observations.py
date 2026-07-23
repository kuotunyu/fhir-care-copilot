"""get_recent_observations:最近的觀察值(生命徵象/檢驗結果等),可依類別篩選。

Observation 數值可能是 ``valueQuantity``、``valueCodeableConcept``、``valueString``,
或以 ``component[]`` 呈現多值量測(如血壓的收縮壓/舒張壓)——四種都要處理。前三種 +
component 已對真實 100 位病患資料(19,550 筆 Observation)完整驗證涵蓋所有出現過的
value[x] 形式(M2 審查,2026-07-19);``valueString`` 常見於 social-history 類別
(如居住狀況、受虐狀況),對長照個案特別重要,漏接會讓已存在的事實被誤判成無資料。

已知資料瑕疵(不在此處理,僅記錄):真實資料中 Left ventricular Ejection fraction
的 category code 誤植為單數 ``vital-sign``(標準應為複數 ``vital-signs``),
19,550 筆中僅 5 筆受影響。以 ``category="vital-signs"`` 篩選查不到這幾筆——
屬於上游資料的極少數不一致,暫不在工具層做別名正規化。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fhir_copilot.fhir_utils import coding_text, datetime_sort_key
from fhir_copilot.store.base import FHIRStore, JsonDict, UnknownPatientError
from fhir_copilot.tools.base import Evidence, ToolErrorCode, resource_evidence


class GetRecentObservationsInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    patient_id: str
    category: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class ObservationSummary(BaseModel):
    model_config = ConfigDict(strict=True)

    display: str
    value_display: str | None
    effective_date: str | None
    category: str | None


class GetRecentObservationsResult(BaseModel):
    model_config = ConfigDict(strict=True)

    ok: bool
    error: Literal[ToolErrorCode.PATIENT_NOT_FOUND] | None = None
    observations: list[ObservationSummary] = []
    evidence: list[Evidence] = []


def _category_code(observation: JsonDict) -> str | None:
    categories = observation.get("category") or []
    if not categories:
        return None
    coding = categories[0].get("coding") or []
    if not coding:
        return None
    code = coding[0].get("code")
    return str(code) if code else None


def _quantity_display(quantity: JsonDict) -> str:
    value = quantity.get("value")
    unit = quantity.get("unit") or quantity.get("code") or ""
    return f"{value} {unit}".strip()


def _value_display(observation: JsonDict) -> str | None:
    if "valueQuantity" in observation:
        return _quantity_display(observation["valueQuantity"])
    if "valueCodeableConcept" in observation:
        return coding_text(observation["valueCodeableConcept"])
    if "valueString" in observation:
        return str(observation["valueString"])
    components = observation.get("component") or []
    if components:
        parts = []
        for comp in components:
            label = coding_text(comp.get("code")) or "?"
            quantity = comp.get("valueQuantity")
            value = _quantity_display(quantity) if quantity else "?"
            parts.append(f"{label}: {value}")
        return "; ".join(parts)
    return None


def get_recent_observations(
    store: FHIRStore, params: GetRecentObservationsInput
) -> GetRecentObservationsResult:
    try:
        store.get_patient(params.patient_id)
    except UnknownPatientError:
        return GetRecentObservationsResult(ok=False, error=ToolErrorCode.PATIENT_NOT_FOUND)

    resources = store.get_resources(params.patient_id, "Observation")
    if params.category is not None:
        resources = [r for r in resources if _category_code(r) == params.category]
    # 用真正的 datetime 比較,不能直接比字串——真實資料混用 -04:00/-05:00 位移時
    # 字串排序會與實際時間相反(M2 審查發現,見 fhir_utils.datetime_sort_key)
    resources.sort(key=lambda r: datetime_sort_key(r.get("effectiveDateTime")), reverse=True)
    resources = resources[: params.limit]

    observations: list[ObservationSummary] = []
    evidence: list[Evidence] = []
    for obs in resources:
        effective = obs.get("effectiveDateTime")
        observations.append(
            ObservationSummary(
                display=coding_text(obs.get("code")) or "(未知觀察項目)",
                value_display=_value_display(obs),
                effective_date=effective,
                category=_category_code(obs),
            )
        )
        evidence.append(resource_evidence(obs, "effectiveDateTime", effective))

    return GetRecentObservationsResult(ok=True, observations=observations, evidence=evidence)
